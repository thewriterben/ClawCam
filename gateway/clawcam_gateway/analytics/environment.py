"""Environmental telemetry report — temperature, humidity, pressure over time.

Health records now carry promoted `temperature_c` / `humidity_percent` / `pressure_hpa`
columns (Conservation Grid G0). This turns a batch of those readings into the numbers a
field operator (or the brain) reasons about: current value, range, mean, direction of
travel, and a per-day series — for each quantity that's present.

Pure and storage-agnostic: it takes reading dicts with a ``timestamp`` and any of the
three quantities; no DB or framework imports, so it unit-tests in isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_QUANTITIES = ("temperature_c", "humidity_percent", "pressure_hpa")


def _local_date(ts: str, tz_offset_hours: int) -> str | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + timedelta(hours=tz_offset_hours)).date().isoformat()


def _trend(values: list[float]) -> str:
    """Rising / falling / steady by comparing the mean of the earlier vs later half."""
    n = len(values)
    if n < 2:
        return "steady"
    half = n // 2
    early = values[:half]
    late = values[n - half:]
    if not early or not late:
        return "steady"
    a = sum(early) / len(early)
    b = sum(late) / len(late)
    # Dead-band relative to the data's own spread (not its offset) — pressure sits near
    # ~1013 hPa but a few hPa is a real trend, so a %-of-value band would be far too wide.
    eps = max((max(values) - min(values)) * 0.05, 1e-9)
    if b > a + eps:
        return "rising"
    if b < a - eps:
        return "falling"
    return "steady"


def build_environment_report(
    readings: list[dict[str, Any]], tz_offset_hours: int = 0
) -> dict[str, Any]:
    """Summarise environmental telemetry per quantity.

    Args:
        readings:        Rows with ``timestamp`` and any of ``temperature_c`` /
                         ``humidity_percent`` / ``pressure_hpa`` (as from
                         ``GatewayDatabase.environment_series``). Order-independent.
        tz_offset_hours: Shift UTC to local time for the daily series.

    Returns ``reading_count`` and a ``quantities`` map; each present quantity carries
    ``count``, ``min``, ``max``, ``mean``, ``latest`` (value at the newest timestamp),
    ``trend`` (rising/falling/steady, oldest→newest), and a ``daily`` list of
    ``{date, mean}``. Quantities with no data are omitted.
    """
    ordered = sorted(readings, key=lambda r: r.get("timestamp") or "")
    quantities: dict[str, Any] = {}

    for q in _QUANTITIES:
        series = [
            (r.get("timestamp") or "", float(r[q]))
            for r in ordered
            if r.get(q) is not None
        ]
        if not series:
            continue
        values = [v for _, v in series]
        # Per-day means (local date).
        by_day: dict[str, list[float]] = {}
        for ts, v in series:
            date = _local_date(ts, tz_offset_hours)
            if date is not None:
                by_day.setdefault(date, []).append(v)
        daily = [
            {"date": d, "mean": round(sum(vs) / len(vs), 2)}
            for d, vs in sorted(by_day.items())
        ]
        quantities[q] = {
            "count": len(values),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "mean": round(sum(values) / len(values), 2),
            "latest": round(series[-1][1], 2),  # newest timestamp (series is sorted asc)
            "trend": _trend(values),
            "daily": daily,
        }

    return {
        "tz_offset_hours": tz_offset_hours,
        "reading_count": len(readings),
        "quantities": quantities,
    }
