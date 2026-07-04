"""Period-over-period comparison — "how does this window compare to the last?".

Given two detection sets (a *current* window and a *previous* window of comparable
length), produces the deltas an operator actually cares about: did overall activity go up
or down, which subjects are newly present, which disappeared, whose rates moved most, and
whether the dominant subject changed.

Pure and storage-agnostic — composes the other pure builders, so it unit-tests in
isolation without a database.
"""

from __future__ import annotations

from typing import Any

from .diversity import build_diversity_report


def _counts(detections: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in detections:
        subject = d.get("top_species") or d.get("top_label") or "unknown"
        counts[subject] = counts.get(subject, 0) + 1
    return counts


def _pct_change(current: float, previous: float) -> float | None:
    """Percent change from previous→current. ``None`` when previous is 0 (undefined)."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100.0, 1)


def _direction(delta: int) -> str:
    return "up" if delta > 0 else "down" if delta < 0 else "flat"


def build_comparison_report(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    current_label: str = "current",
    previous_label: str = "previous",
) -> dict[str, Any]:
    """Compare a current detection window against a previous one.

    Args:
        current:        Detection rows for the current window.
        previous:       Detection rows for the previous (baseline) window.
        current_label:  Human name for the current window (e.g. ``"this week"``).
        previous_label: Human name for the baseline window (e.g. ``"last week"``).

    Returns totals + percent change, the set of ``new_subjects`` (present now, absent
    before) and ``dropped_subjects`` (present before, absent now), per-subject count
    deltas sorted by magnitude, a richness delta, whether the dominant subject changed,
    and a one-line ``headline``.
    """
    cur_counts = _counts(current)
    prev_counts = _counts(previous)
    cur_total = len(current)
    prev_total = len(previous)

    cur_subjects = set(cur_counts)
    prev_subjects = set(prev_counts)
    new_subjects = sorted(cur_subjects - prev_subjects)
    dropped_subjects = sorted(prev_subjects - cur_subjects)

    per_subject = []
    for subject in sorted(cur_subjects | prev_subjects):
        c = cur_counts.get(subject, 0)
        p = prev_counts.get(subject, 0)
        per_subject.append(
            {
                "subject": subject,
                "current": c,
                "previous": p,
                "delta": c - p,
                "pct_change": _pct_change(c, p),
                "direction": _direction(c - p),
            }
        )
    per_subject.sort(key=lambda s: abs(s["delta"]), reverse=True)

    cur_div = build_diversity_report(current)
    prev_div = build_diversity_report(previous)
    dominant_changed = cur_div["dominant_subject"] != prev_div["dominant_subject"]

    total_delta = cur_total - prev_total
    headline_bits = [
        f"{cur_total} vs {prev_total} detections ({_direction(total_delta)}"
    ]
    pct = _pct_change(cur_total, prev_total)
    headline_bits[0] += f", {pct:+.1f}%)" if pct is not None else ")"
    if new_subjects:
        headline_bits.append(f"new: {', '.join(new_subjects)}")
    if dropped_subjects:
        headline_bits.append(f"gone: {', '.join(dropped_subjects)}")
    if dominant_changed and cur_div["dominant_subject"]:
        headline_bits.append(
            f"dominant {prev_div['dominant_subject']}→{cur_div['dominant_subject']}"
        )

    return {
        "current_label": current_label,
        "previous_label": previous_label,
        "headline": "; ".join(headline_bits) + ".",
        "total_current": cur_total,
        "total_previous": prev_total,
        "total_delta": total_delta,
        "total_pct_change": pct,
        "richness_current": cur_div["richness"],
        "richness_previous": prev_div["richness"],
        "richness_delta": cur_div["richness"] - prev_div["richness"],
        "new_subjects": new_subjects,
        "dropped_subjects": dropped_subjects,
        "dominant_changed": dominant_changed,
        "dominant_current": cur_div["dominant_subject"],
        "dominant_previous": prev_div["dominant_subject"],
        "by_subject": per_subject,
    }
