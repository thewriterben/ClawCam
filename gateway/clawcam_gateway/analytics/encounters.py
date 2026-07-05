"""Encounter sessionization — collapse lingering captures into independent events.

A camera trap fires repeatedly while an animal is in frame, so raw detection counts
overstate activity (a deer that browses for two minutes can trigger a dozen frames). The
ecology-standard remedy is the *independent detection event*: consecutive detections of
the same subject separated by less than a gap threshold count as one encounter.

This groups detections per subject into encounters and reports both the raw and the
deduplicated counts, so downstream activity/diversity numbers can use "encounters" rather
than "frames" when that is the honest unit.

Pure and storage-agnostic — operates on already-fetched detection dicts, no database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 ``ran_at`` into an aware UTC datetime, or ``None``."""
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _subject(det: dict[str, Any]) -> str:
    return det.get("top_species") or det.get("top_label") or "unknown"


def build_encounter_report(
    detections: list[dict[str, Any]],
    gap_minutes: int = 30,
) -> dict[str, Any]:
    """Group detections into independent encounters per subject.

    Args:
        detections: Detection rows with ``top_species``/``top_label`` and ISO ``ran_at``.
        gap_minutes: Consecutive same-subject detections closer than this (in minutes)
                     belong to the same encounter; a larger gap starts a new one.

    Returns per-subject encounter vs raw-detection counts (with a ``compression`` ratio),
    the encounter list (subject, ``start``/``end`` ISO, ``detections`` count, and
    ``duration_s``), and totals. Detections with an unparseable timestamp are ignored.
    """
    gap_s = max(0, int(gap_minutes)) * 60

    # Bucket parseable detections by subject, each as (datetime, detection).
    by_subject: dict[str, list[datetime]] = {}
    ignored = 0
    for d in detections:
        ts = _parse_ts(d.get("ran_at"))
        if ts is None:
            ignored += 1
            continue
        by_subject.setdefault(_subject(d), []).append(ts)

    encounters: list[dict[str, Any]] = []
    per_subject: dict[str, dict[str, Any]] = {}
    for subject, times in by_subject.items():
        times.sort()
        run_start = times[0]
        run_last = times[0]
        run_count = 1

        def _flush(start: datetime, end: datetime, count: int) -> None:
            encounters.append({
                "subject": subject,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "detections": count,
                "duration_s": int((end - start).total_seconds()),
            })

        for ts in times[1:]:
            if (ts - run_last).total_seconds() > gap_s:
                _flush(run_start, run_last, run_count)
                run_start, run_last, run_count = ts, ts, 1
            else:
                run_last, run_count = ts, run_count + 1
        _flush(run_start, run_last, run_count)

        enc_count = sum(1 for e in encounters if e["subject"] == subject)
        per_subject[subject] = {
            "encounters": enc_count,
            "detections": len(times),
            "compression": round(len(times) / enc_count, 2) if enc_count else 0.0,
        }

    encounters.sort(key=lambda e: e["start"])
    total_detections = sum(s["detections"] for s in per_subject.values())
    return {
        "gap_minutes": int(gap_minutes),
        "total_encounters": len(encounters),
        "total_detections": total_detections,
        "ignored_no_timestamp": ignored,
        "by_subject": per_subject,
        "encounters": encounters,
    }
