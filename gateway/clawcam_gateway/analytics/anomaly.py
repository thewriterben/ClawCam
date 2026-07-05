"""Daily anomaly detection — flag unusually busy or quiet days.

Trends tell you the *direction* a site is moving; this catches individual days that break
from the site's own baseline — a sudden surge of detections (a herd moving through, a
gate left open) or a suspicious drop (a camera knocked askew, an obstruction). Each day's
detection count is scored against the mean and standard deviation of the whole series;
days beyond a z-score threshold are surfaced as spikes or drops.

Pure and storage-agnostic — operates on already-fetched detection dicts with ISO
``ran_at`` timestamps; no database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Any


def _day_of(value: Any, tz_offset_hours: int) -> str | None:
    """Return the local calendar day (``YYYY-MM-DD``) for an ISO timestamp, or ``None``."""
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc) + timedelta(hours=tz_offset_hours)
    return dt.date().isoformat()


def build_anomaly_report(
    detections: list[dict[str, Any]],
    z_threshold: float = 2.0,
    tz_offset_hours: int = 0,
) -> dict[str, Any]:
    """Score each day's detection count against the series baseline and flag outliers.

    Args:
        detections:      Rows with an ISO ``ran_at`` timestamp.
        z_threshold:     A day is anomalous when ``|z| >= z_threshold`` (default 2.0).
        tz_offset_hours: Local-time shift for day bucketing.

    Returns the daily series (each with ``date``, ``count``, ``z``, ``anomaly``, and
    ``kind`` of ``spike``/``drop``/``normal``), plus a summary (mean, population stdev,
    day count, anomaly count, busiest/quietest day). Fewer than two days, or a flat
    series (stdev 0), yields no anomalies.
    """
    counts: dict[str, int] = {}
    ignored = 0
    for d in detections:
        day = _day_of(d.get("ran_at"), tz_offset_hours)
        if day is None:
            ignored += 1
            continue
        counts[day] = counts.get(day, 0) + 1

    days = sorted(counts)
    n = len(days)
    if n == 0:
        return {"days": 0, "mean": 0.0, "stdev": 0.0, "z_threshold": z_threshold,
                "anomalies": 0, "ignored_no_timestamp": ignored, "series": []}

    values = [counts[d] for d in days]
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n  # population variance
    stdev = sqrt(var)

    series: list[dict[str, Any]] = []
    anomalies = 0
    for day_key in days:  # 'd' above is a detection dict; don't shadow it
        c = counts[day_key]
        z = round((c - mean) / stdev, 2) if stdev > 0 else 0.0
        is_anom = stdev > 0 and n >= 2 and abs(z) >= z_threshold
        kind = "normal"
        if is_anom:
            anomalies += 1
            kind = "spike" if z > 0 else "drop"
        series.append({"date": day_key, "count": c, "z": z, "anomaly": is_anom, "kind": kind})

    busiest = max(days, key=lambda d: counts[d])
    quietest = min(days, key=lambda d: counts[d])
    return {
        "days": n,
        "mean": round(mean, 2),
        "stdev": round(stdev, 2),
        "z_threshold": z_threshold,
        "anomalies": anomalies,
        "busiest_day": busiest,
        "quietest_day": quietest,
        "ignored_no_timestamp": ignored,
        "series": series,
    }
