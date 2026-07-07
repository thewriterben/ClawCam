"""Species co-occurrence — which subjects use the site at the *same* times?

Two complementary signals ecologists read off camera-trap data:

* **Temporal co-occurrence** — do two species show up in the same short time windows?
  Detections are binned into fixed windows (default 60 min); for each species pair the
  Jaccard index over windows (``shared / either``) measures how often they coincide.
* **Activity overlap** — do their daily rhythms line up? Each species' hour-of-day
  distribution is compared with Schoener's overlap ``D = 1 − ½·Σ|pₐ−p_b|`` (1.0 =
  identical daily timing, 0.0 = disjoint). A nocturnal predator and a diurnal bird score
  low even if both are common.

High window-Jaccard *and* high activity-overlap suggests genuine co-use (predator–prey,
shared resource); high activity-overlap with low window-Jaccard suggests same schedule but
spatial/temporal avoidance. Pure and storage-agnostic — takes detection dicts with
``top_species``/``top_label`` and ``ran_at``; no DB or framework imports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations
from typing import Any


def _parse_dt(ran_at: str) -> datetime | None:
    """Parse an ISO 8601 timestamp to a tz-aware UTC datetime, or None."""
    if not ran_at:
        return None
    try:
        dt = datetime.fromisoformat(ran_at.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _local_hour(dt: datetime, tz_offset_hours: int) -> int:
    return (dt.hour + tz_offset_hours) % 24


def _overlap(a_hourly: list[int], b_hourly: list[int]) -> float:
    """Schoener's overlap of two hour-of-day histograms (0..1)."""
    sa, sb = sum(a_hourly), sum(b_hourly)
    if sa == 0 or sb == 0:
        return 0.0
    return round(1.0 - 0.5 * sum(abs(a_hourly[h] / sa - b_hourly[h] / sb) for h in range(24)), 3)


def build_cooccurrence_report(
    detections: list[dict[str, Any]],
    window_minutes: int = 60,
    tz_offset_hours: int = 0,
    min_shared: int = 1,
) -> dict[str, Any]:
    """Score temporal co-occurrence and activity overlap for every species pair.

    Args:
        detections:      Rows with ``top_species``/``top_label`` and ``ran_at`` (ISO 8601).
        window_minutes:  Width of the co-occurrence time bin (default 60).
        tz_offset_hours: Shift UTC to local time for the hour-of-day overlap only.
        min_shared:      Drop pairs sharing fewer than this many windows (default 1).

    Returns a JSON-serialisable report: ``windows`` (distinct occupied bins),
    ``distinct_subjects``, per-subject window counts, and a ``pairs`` list (strongest
    association first) each with ``shared_windows``, ``jaccard``, ``activity_overlap``,
    and each subject's window count. ``strongest`` names the top pair (or ``None``).
    """
    span = max(1, int(window_minutes)) * 60
    # window index -> set of subjects; subject -> set of window indices; subject -> hourly.
    win_subjects: dict[int, set[str]] = {}
    subj_windows: dict[str, set[int]] = {}
    subj_hourly: dict[str, list[int]] = {}
    used = 0

    for det in detections:
        subject = det.get("top_species") or det.get("top_label")
        if not subject:
            continue
        dt = _parse_dt(det.get("ran_at") or "")
        if dt is None:
            continue
        used += 1
        widx = int(dt.timestamp() // span)
        win_subjects.setdefault(widx, set()).add(subject)
        subj_windows.setdefault(subject, set()).add(widx)
        h = subj_hourly.setdefault(subject, [0] * 24)
        h[_local_hour(dt, tz_offset_hours)] += 1

    subjects = sorted(subj_windows)
    pairs: list[dict[str, Any]] = []
    for a, b in combinations(subjects, 2):
        wa, wb = subj_windows[a], subj_windows[b]
        shared = len(wa & wb)
        if shared < min_shared:
            continue
        union = len(wa | wb)
        pairs.append({
            "a": a,
            "b": b,
            "shared_windows": shared,
            "a_windows": len(wa),
            "b_windows": len(wb),
            "jaccard": round(shared / union, 3) if union else 0.0,
            "activity_overlap": _overlap(subj_hourly[a], subj_hourly[b]),
        })

    pairs.sort(key=lambda p: (-p["jaccard"], -p["activity_overlap"], p["a"], p["b"]))
    strongest = {"a": pairs[0]["a"], "b": pairs[0]["b"], "jaccard": pairs[0]["jaccard"]} if pairs else None

    return {
        "window_minutes": max(1, int(window_minutes)),
        "tz_offset_hours": tz_offset_hours,
        "total_detections": used,
        "windows": len(win_subjects),
        "distinct_subjects": len(subjects),
        "subjects": [{"subject": s, "windows": len(subj_windows[s])} for s in subjects],
        "pairs": pairs,
        "strongest": strongest,
    }
