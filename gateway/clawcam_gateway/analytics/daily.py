"""Daily site section — the analytics roll-up folded into the daily summary.

``generate_daily_summary`` historically reported only *event* counts (captures, uploads,
classifications). This adds the ecology picture for the same day: a one-day
:func:`build_site_report` (activity + trends + diversity + alert digest) plus a compact
one-line ``sentence`` an operator can read at a glance.

Pure and storage-agnostic — it composes the other pure builders, so it unit-tests in
isolation without a database.
"""

from __future__ import annotations

from typing import Any

from .site import build_site_report


def build_daily_site_section(
    detections: list[dict[str, Any]],
    alert_events: list[dict[str, Any]] | None = None,
    tz_offset_hours: int = 0,
) -> dict[str, Any]:
    """Build the site report for one day plus a one-line summary sentence.

    Args:
        detections:      The day's detection rows (``top_species``/``top_label`` + ``ran_at``).
        alert_events:    The day's fired ``alert_events`` rows (optional).
        tz_offset_hours: Local-time shift for hour/day bucketing.

    Returns ``{"sentence": str, "report": <site report>}``. The ``report`` is a full
    :func:`build_site_report` with a ``"1d"`` digest window label.
    """
    report = build_site_report(
        detections,
        alert_events=alert_events,
        tz_offset_hours=tz_offset_hours,
        digest_window_label="1d",
    )
    h = report["headline"]

    if h["total_detections"] == 0:
        sentence = "No animal detections recorded."
    else:
        parts = [
            f"{h['total_detections']} detections across "
            f"{h['distinct_subjects']} subject(s)"
        ]
        if h["top_subject"]:
            parts.append(f"led by {h['top_subject']}")
        if h["rising_subjects"]:
            parts.append(f"rising: {', '.join(h['rising_subjects'])}")
        if h["falling_subjects"]:
            parts.append(f"falling: {', '.join(h['falling_subjects'])}")
        if h["total_alerts"]:
            suppressed = h["alerts_suppressed"]
            tail = f"{h['total_alerts']} alert(s)"
            if suppressed:
                tail += f" ({suppressed} suppressed)"
            parts.append(tail)
        sentence = "; ".join(parts) + "."

    return {"sentence": sentence, "report": report}
