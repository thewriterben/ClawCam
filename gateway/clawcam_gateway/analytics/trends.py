"""Detection trend report — is each subject's activity rising or falling?

Where ``activity.py`` answers *when in the day* a species is active, this answers *how the
day-over-day rate is changing* — the question behind "are the deer sightings increasing at
this site?". It buckets detections by calendar day (local, after a tz offset), then per
subject compares the average daily rate of the earlier half of its active days against the
later half to label a trend (rising / falling / steady).

Pure and storage-agnostic: takes the detection dicts ``list_inference_results`` returns and
gives back a JSON-serialisable summary. No DB or framework imports.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _date_of(ran_at: str, tz_offset_hours: int) -> str | None:
    """Local calendar date (``YYYY-MM-DD``) for an ISO 8601 timestamp, or ``None``."""
    if not ran_at:
        return None
    try:
        dt = datetime.fromisoformat(ran_at.strip().replace("Z", "+00:00"))
    except ValueError:
        head = ran_at.split("T", 1)[0]
        return head if len(head) == 10 else None
    dt = dt + timedelta(hours=tz_offset_hours)
    return dt.date().isoformat()


def _trend(daily_counts: list[int]) -> str:
    """Classify a chronological list of per-day counts into a trend label.

    Compares the mean daily rate of the earlier half of active days to the later half, so
    an uneven split (odd number of days) doesn't bias the verdict.
    """
    n = len(daily_counts)
    if n < 2:
        return "steady"
    mid = n // 2
    earlier = sum(daily_counts[:mid]) / mid
    later = sum(daily_counts[mid:]) / (n - mid)
    if later > earlier * 1.2:
        return "rising"
    if later < earlier * 0.8:
        return "falling"
    return "steady"


def build_trend_report(
    detections: list[dict[str, Any]], tz_offset_hours: int = 0
) -> dict[str, Any]:
    """Summarise day-over-day detection trends per subject.

    Args:
        detections:      Rows with ``top_species``/``top_label`` and ``ran_at`` (ISO 8601).
        tz_offset_hours: Shift UTC to local time before taking the calendar date.

    Returns a JSON-serialisable report: overall ``daily_totals`` time series, and a
    ``species`` list (most detections first) each with ``total``, a ``trend`` label,
    ``busiest_day``, ``first_day``/``last_day``, and its own ``daily`` series.
    """
    per: dict[str, dict[str, int]] = {}
    all_days: dict[str, int] = {}
    used = 0
    for det in detections:
        subject = det.get("top_species") or det.get("top_label")
        if not subject:
            continue
        day = _date_of(det.get("ran_at") or "", tz_offset_hours)
        if day is None:
            continue
        used += 1
        counts = per.setdefault(subject, {})
        counts[day] = counts.get(day, 0) + 1
        all_days[day] = all_days.get(day, 0) + 1

    species = []
    for subject, counts in per.items():
        days_sorted = sorted(counts.items())  # [(date, count)], chronological
        daily_counts = [c for _, c in days_sorted]
        busiest_day = max(days_sorted, key=lambda kv: kv[1])[0]
        species.append({
            "subject": subject,
            "total": sum(daily_counts),
            "trend": _trend(daily_counts),
            "busiest_day": busiest_day,
            "first_day": days_sorted[0][0],
            "last_day": days_sorted[-1][0],
            "daily": [{"date": d, "count": c} for d, c in days_sorted],
        })
    species.sort(key=lambda s: (-s["total"], s["subject"]))

    return {
        "tz_offset_hours": tz_offset_hours,
        "total_detections": used,
        "distinct_subjects": len(species),
        "days_span": len(all_days),
        "daily_totals": [{"date": d, "count": c} for d, c in sorted(all_days.items())],
        "species": species,
    }
