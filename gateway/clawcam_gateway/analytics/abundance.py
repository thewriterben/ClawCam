"""Relative abundance index (RAI) — effort-normalised detection rates.

Raw counts can't be compared across species or sites because they conflate *how much
animal* with *how long the camera watched*. The camera-trap standard is the Relative
Abundance Index: detections per 100 trap-days. This builder computes it per subject over
the survey's trap-day effort.

Effort (``trap_days``) is the number of days the camera was active. When it isn't supplied
explicitly it's estimated from the detection record as the inclusive calendar span from the
first to the last detection (``last − first + 1`` days) — a reasonable proxy for a camera
that ran continuously, and the report flags which method was used so a caller can pass real
effort metadata when they have it.

Pure and storage-agnostic: takes detection dicts with ``top_species``/``top_label`` and
``ran_at``; no DB or framework imports.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _local_date(ran_at: str, tz_offset_hours: int) -> str | None:
    """Local calendar date (YYYY-MM-DD) for an ISO timestamp, or None if unparseable."""
    if not ran_at:
        return None
    try:
        dt = datetime.fromisoformat(ran_at.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(hours=tz_offset_hours)).date().isoformat()


def build_abundance_report(
    detections: list[dict[str, Any]],
    tz_offset_hours: int = 0,
    trap_days: int | None = None,
) -> dict[str, Any]:
    """Per-subject relative abundance index (detections per 100 trap-days).

    Args:
        detections:      Rows with ``top_species``/``top_label`` and ``ran_at`` (ISO 8601).
        tz_offset_hours: Shift UTC to local time for day bucketing.
        trap_days:       Survey effort in camera-active days. If ``None`` (default) it is
                         estimated as the inclusive first→last detection calendar span.

    Returns ``trap_days``, ``trap_days_source`` (``"provided"`` or ``"span"``),
    ``total_detections`` used, ``distinct_subjects``, and a ``species`` list (highest RAI
    first) each with ``count``, ``days_present``, and ``rai`` (detections per 100
    trap-days). Empty input yields zero effort and no species.
    """
    counts: dict[str, int] = {}
    days_present: dict[str, set[str]] = {}
    all_dates: set[str] = set()
    used = 0

    for det in detections:
        subject = det.get("top_species") or det.get("top_label")
        if not subject:
            continue
        date = _local_date(det.get("ran_at") or "", tz_offset_hours)
        if date is None:
            continue
        used += 1
        counts[subject] = counts.get(subject, 0) + 1
        days_present.setdefault(subject, set()).add(date)
        all_dates.add(date)

    if trap_days is not None:
        effort = max(0, int(trap_days))
        source = "provided"
    elif all_dates:
        first = min(all_dates)
        last = max(all_dates)
        effort = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days + 1
        source = "span"
    else:
        effort = 0
        source = "span"

    species = []
    for subject, count in counts.items():
        rai = round(count / effort * 100.0, 2) if effort > 0 else None
        species.append({
            "subject": subject,
            "count": count,
            "days_present": len(days_present[subject]),
            "rai": rai,
        })
    # Rank by RAI (None sinks), then count, then name for stability.
    species.sort(key=lambda s: (-(s["rai"] if s["rai"] is not None else -1), -s["count"], s["subject"]))

    return {
        "tz_offset_hours": tz_offset_hours,
        "trap_days": effort,
        "trap_days_source": source,
        "total_detections": used,
        "distinct_subjects": len(species),
        "species": species,
    }
