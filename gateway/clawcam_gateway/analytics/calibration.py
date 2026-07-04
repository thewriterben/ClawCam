"""Confidence calibration from human review — is the model's confidence trustworthy?

Every reviewed detection is ground truth: ``verified``/``corrected`` means the detection
was a real hit, ``rejected`` means it was a false positive. Pooling those, this measures
whether higher confidence actually means higher correctness (calibration) and recommends
a confidence threshold above which precision meets a target — the number you'd use to
auto-accept detections and only send the rest to a human.

Pure and storage-agnostic — operates on already-fetched detection dicts carrying
``top_confidence`` and ``review_state``; no database.
"""

from __future__ import annotations

from typing import Any

_POSITIVE = {"verified", "corrected"}   # human confirmed the detection was real
_NEGATIVE = {"rejected"}                # human marked it a false positive


def build_calibration_report(
    rows: list[dict[str, Any]],
    buckets: int = 10,
    target_precision: float = 0.9,
) -> dict[str, Any]:
    """Assess confidence calibration over reviewed detections and suggest a threshold.

    Args:
        rows:             Detection dicts with ``top_confidence`` and ``review_state``.
                          Only reviewed rows (verified/corrected/rejected) are used.
        buckets:          Number of equal-width confidence bins in ``[0, 1]``.
        target_precision: Desired precision for the recommended auto-accept threshold.

    Returns per-bucket confirmed/rejected counts and confirmed-rate, the overall
    precision, whether confidence is well-calibrated (confirmed-rate non-decreasing across
    populated bins), and a ``suggested_threshold`` — the lowest confidence at which
    accepting everything above it still meets ``target_precision`` (``None`` if no
    threshold does).
    """
    labeled: list[tuple[float, bool]] = []
    for r in rows:
        state = str(r.get("review_state") or "").strip().lower()
        if state in _POSITIVE:
            labeled.append((float(r.get("top_confidence") or 0.0), True))
        elif state in _NEGATIVE:
            labeled.append((float(r.get("top_confidence") or 0.0), False))

    n = len(labeled)
    if n == 0:
        return {
            "reviewed": 0,
            "message": "no reviewed detections (verified/corrected/rejected) to calibrate on",
            "buckets": [],
            "suggested_threshold": None,
        }

    nb = max(1, int(buckets))
    bins = [{"lo": round(i / nb, 3), "hi": round((i + 1) / nb, 3),
             "n": 0, "confirmed": 0, "rejected": 0} for i in range(nb)]
    for conf, is_pos in labeled:
        idx = min(nb - 1, int(conf * nb))  # 1.0 lands in the top bin
        b = bins[idx]
        b["n"] += 1
        b["confirmed" if is_pos else "rejected"] += 1
    for b in bins:
        b["confirmed_rate"] = round(b["confirmed"] / b["n"], 3) if b["n"] else None

    # Well-calibrated ≈ confirmed-rate never drops as confidence rises (populated bins).
    rates = [b["confirmed_rate"] for b in bins if b["confirmed_rate"] is not None]
    well_calibrated = all(a <= b + 1e-9 for a, b in zip(rates, rates[1:]))

    # Recommended threshold: deepest prefix (top-down by confidence) whose precision still
    # meets the target — accepting everything at/above it yields >= target_precision.
    labeled.sort(key=lambda t: t[0], reverse=True)
    tp = fp = 0
    suggested: float | None = None
    accepted = 0
    prec_at = None
    for conf, is_pos in labeled:
        if is_pos:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        if precision >= target_precision:
            suggested = conf
            accepted = tp + fp
            prec_at = round(precision, 3)

    n_pos = sum(1 for _, p in labeled if p)
    return {
        "reviewed": n,
        "confirmed": n_pos,
        "rejected": n - n_pos,
        "overall_precision": round(n_pos / n, 3),
        "target_precision": target_precision,
        "well_calibrated": well_calibrated,
        "suggested_threshold": suggested,
        "accepted_at_threshold": accepted,
        "precision_at_threshold": prec_at,
        "buckets": bins,
    }
