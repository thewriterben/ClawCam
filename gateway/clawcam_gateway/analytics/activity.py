"""Species activity report — *when* is each subject active?

Camera-trap detections carry a timestamp (``ran_at``) and a subject (``top_species`` or
``top_label``). This rolls a batch of detections into a per-subject hour-of-day profile:
total count, an hourly histogram, first/last seen, the peak hour, and a **diel pattern**
classification (nocturnal / diurnal / crepuscular / cathemeral) — the kind of question a
wildlife operator actually asks ("are the coyotes nocturnal here?").

Pure and storage-agnostic: it takes a list of detection dicts (as returned by
``GatewayDatabase.list_inference_results``) and returns a JSON-serialisable summary. No DB
or framework imports, so it unit-tests in isolation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Hour-of-day bands (local time after the tz offset). Dawn/dusk get their own band so a
# crepuscular signal isn't washed out by the broad day/night split.
_NIGHT: frozenset[int] = frozenset({19, 20, 21, 22, 23, 0, 1, 2, 3, 4})
_DAY: frozenset[int] = frozenset({7, 8, 9, 10, 11, 12, 13, 14, 15, 16})
_CREPUSCULAR: frozenset[int] = frozenset({5, 6, 17, 18})


def _hour_of(ran_at: str, tz_offset_hours: int) -> int | None:
    """Local hour-of-day (0–23) for an ISO 8601 timestamp, or ``None`` if unparseable."""
    if not ran_at:
        return None
    try:
        dt = datetime.fromisoformat(ran_at.strip().replace("Z", "+00:00"))
        hour = dt.hour
    except ValueError:
        # Best-effort fallback: the "T HH" portion of an ISO-ish string.
        try:
            hour = int(ran_at.split("T", 1)[1][:2])
        except (IndexError, ValueError):
            return None
    return (hour + tz_offset_hours) % 24


def _diel_pattern(hourly: list[int]) -> str:
    """Classify a 24-bucket histogram into a diel activity pattern."""
    total = sum(hourly)
    if total == 0:
        return "unknown"
    night = sum(hourly[h] for h in _NIGHT) / total
    day = sum(hourly[h] for h in _DAY) / total
    crepuscular = sum(hourly[h] for h in _CREPUSCULAR) / total
    if crepuscular >= 0.5:
        return "crepuscular"
    if night >= 0.6:
        return "nocturnal"
    if day >= 0.6:
        return "diurnal"
    return "cathemeral"  # active across the day/night cycle


def build_activity_report(
    detections: list[dict[str, Any]], tz_offset_hours: int = 0
) -> dict[str, Any]:
    """Summarise activity timing per subject from a batch of detections.

    Args:
        detections:      Rows with ``top_species``/``top_label`` and ``ran_at`` (ISO 8601),
                         e.g. from ``GatewayDatabase.list_inference_results``.
        tz_offset_hours: Shift UTC timestamps to local time for hour-of-day bucketing
                         (e.g. ``-8`` for US Pacific). Default 0 (UTC).

    Returns a JSON-serialisable report: ``total_detections`` used, ``distinct_subjects``,
    and a ``species`` list (most frequent first) each with ``count``, ``peak_hour``,
    ``diel_pattern``, ``first_seen``/``last_seen``, and the 24-bucket ``hourly`` histogram.
    """
    per: dict[str, dict[str, Any]] = {}
    used = 0
    for det in detections:
        subject = det.get("top_species") or det.get("top_label")
        if not subject:
            continue
        ran_at = det.get("ran_at") or ""
        hour = _hour_of(ran_at, tz_offset_hours)
        if hour is None:
            continue
        used += 1
        entry = per.get(subject)
        if entry is None:
            entry = {"count": 0, "hourly": [0] * 24, "first_seen": ran_at, "last_seen": ran_at}
            per[subject] = entry
        entry["count"] += 1
        entry["hourly"][hour] += 1
        if ran_at and ran_at < entry["first_seen"]:
            entry["first_seen"] = ran_at
        if ran_at and ran_at > entry["last_seen"]:
            entry["last_seen"] = ran_at

    species = []
    for subject, entry in per.items():
        hourly = entry["hourly"]
        peak_hour = max(range(24), key=lambda h: hourly[h])
        species.append({
            "subject": subject,
            "count": entry["count"],
            "peak_hour": peak_hour,
            "diel_pattern": _diel_pattern(hourly),
            "first_seen": entry["first_seen"],
            "last_seen": entry["last_seen"],
            "hourly": hourly,
        })
    species.sort(key=lambda s: (-s["count"], s["subject"]))

    return {
        "tz_offset_hours": tz_offset_hours,
        "total_detections": used,
        "distinct_subjects": len(species),
        "species": species,
    }
