"""Weather–activity correlation — does detection activity track conditions?

Joins two streams that live apart: detections (``inference_results``, timestamped) and
environmental readings (``health_records``, now carrying promoted temperature / humidity /
pressure columns). Each detection is aligned to its nearest-in-time reading to get the
conditions *when the animal was seen*; detections are then binned by that value and
compared against **exposure** — how many readings fell in each bin — so the result is a
*rate* (detections per reading), not a raw count that just reflects how long each condition
lasted. A Pearson correlation between bin temperature and rate summarizes the direction and
strength ("fox activity rises with temperature here").

Pure and storage-agnostic: detection dicts (``ran_at`` + subject) and reading dicts
(``timestamp`` + the quantity); no DB or framework imports.
"""

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
from typing import Any


def _epoch(ts: str) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _nearest(times: list[float], t: float) -> int:
    """Index of the closest value in the sorted ``times`` to ``t``."""
    i = bisect_left(times, t)
    if i == 0:
        return 0
    if i >= len(times):
        return len(times) - 1
    before, after = times[i - 1], times[i]
    return i if (after - t) < (t - before) else i - 1


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return round(sxy / ((sxx ** 0.5) * (syy ** 0.5)), 3)


def build_weather_activity_report(
    detections: list[dict[str, Any]],
    readings: list[dict[str, Any]],
    quantity: str = "temperature_c",
    bins: int = 5,
    max_gap_minutes: float = 120.0,
) -> dict[str, Any]:
    """Correlate detection activity with an environmental ``quantity``.

    Args:
        detections:      Rows with ``ran_at`` (and ``top_species``/``top_label``).
        readings:        Rows with ``timestamp`` and ``quantity`` (temperature_c etc.).
        quantity:        Which environmental value to bin by (default temperature).
        bins:            Number of equal-width bins across the reading value range.
        max_gap_minutes: A detection is dropped if the nearest reading in time is
                         further than this away (default 120 min).

    Returns per-bin ``exposure`` (readings), ``detections`` and ``rate`` (det/exposure),
    the overall ``correlation`` (Pearson r of bin value vs rate over populated bins),
    the ``peak_bin`` (highest rate), and matched/unmatched detection counts. When there is
    no usable reading data it returns a clear ``message``.
    """
    # Readings that carry the quantity, sorted by time.
    rq = sorted(
        (
            (_epoch(r.get("timestamp") or ""), float(r[quantity]))
            for r in readings
            if r.get(quantity) is not None and _epoch(r.get("timestamp") or "") is not None
        ),
        key=lambda p: p[0],
    )
    if not rq:
        return {
            "quantity": quantity, "readings_used": 0,
            "message": f"no readings with '{quantity}' to correlate against",
            "bins": [], "correlation": None, "peak_bin": None,
            "matched_detections": 0, "unmatched_detections": 0,
        }

    times = [t for t, _ in rq]
    vals = [v for _, v in rq]
    lo, hi = min(vals), max(vals)
    nb = max(1, int(bins))
    width = (hi - lo) / nb if hi > lo else 1.0

    def bin_index(v: float) -> int:
        if hi <= lo:
            return 0
        return min(nb - 1, max(0, int((v - lo) / width)))

    exposure = [0] * nb
    for v in vals:
        exposure[bin_index(v)] += 1

    max_gap_s = max(0.0, float(max_gap_minutes)) * 60.0
    det_counts = [0] * nb
    matched = 0
    unmatched = 0
    for d in detections:
        t = _epoch(d.get("ran_at") or "")
        if t is None:
            unmatched += 1
            continue
        j = _nearest(times, t)
        if abs(times[j] - t) > max_gap_s:
            unmatched += 1
            continue
        det_counts[bin_index(vals[j])] += 1
        matched += 1

    bins_out: list[dict[str, Any]] = []
    for i in range(nb):
        b_lo = round(lo + i * width, 2)
        b_hi = round(lo + (i + 1) * width, 2) if hi > lo else round(hi, 2)
        rate = round(det_counts[i] / exposure[i], 3) if exposure[i] else None
        bins_out.append({
            "lo": b_lo, "hi": b_hi, "mid": round((b_lo + b_hi) / 2.0, 2),
            "exposure": exposure[i], "detections": det_counts[i], "rate": rate,
        })

    populated = [b for b in bins_out if b["rate"] is not None]
    correlation = _pearson([b["mid"] for b in populated], [b["rate"] for b in populated])
    peak = max(populated, key=lambda b: b["rate"]) if populated else None
    peak_bin = {"lo": peak["lo"], "hi": peak["hi"], "rate": peak["rate"]} if peak else None

    return {
        "quantity": quantity,
        "readings_used": len(rq),
        "matched_detections": matched,
        "unmatched_detections": unmatched,
        "bins": bins_out,
        "correlation": correlation,
        "peak_bin": peak_bin,
    }
