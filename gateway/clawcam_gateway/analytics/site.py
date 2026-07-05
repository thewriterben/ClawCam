"""Site report — one operator-facing summary of a deployment.

Stitches the analytics roll-ups into a single answer to "what's happening at this
site?": *when* species are active (`activity`), *how the rates are trending* (`trends`),
*how diverse* it is (`diversity`), *how many real visits* there were (`encounters`, so
the headline carries honest visit counts alongside raw frames), and *what alerted*
(`alerts` digest) — plus a compact ``headline`` an operator (or the brain) can read at a
glance.

Pure and storage-agnostic: it composes the other pure builders (no DB or framework
imports), so it unit-tests in isolation.
"""

from __future__ import annotations

from typing import Any

from clawcam_gateway.alerts.digest import build_alert_digest

from .activity import build_activity_report
from .diversity import build_diversity_report
from .encounters import build_encounter_report
from .trends import build_trend_report


def build_site_report(
    detections: list[dict[str, Any]],
    alert_events: list[dict[str, Any]] | None = None,
    tz_offset_hours: int = 0,
    digest_window_label: str = "",
    encounter_gap_minutes: int = 30,
) -> dict[str, Any]:
    """Combine activity, trend, and alert-digest roll-ups into one site summary.

    Args:
        detections:          Detection rows (``top_species``/``top_label`` + ``ran_at``).
        alert_events:        Fired ``alert_events`` rows for the digest (optional).
        tz_offset_hours:     Local-time shift for the day/hour bucketing.
        digest_window_label: Human span the alert digest covers (e.g. ``"7d"``).

    Returns a report with a ``headline`` (totals + top subject + rising/falling subjects +
    busiest day + alert counts) and the full ``activity``, ``trends``, and ``alerts``
    sub-reports.
    """
    alert_events = alert_events or []
    activity = build_activity_report(detections, tz_offset_hours=tz_offset_hours)
    trends = build_trend_report(detections, tz_offset_hours=tz_offset_hours)
    diversity = build_diversity_report(detections)
    encounters = build_encounter_report(detections, gap_minutes=encounter_gap_minutes)
    alerts = build_alert_digest(alert_events, window_label=digest_window_label)

    top_subject = activity["species"][0]["subject"] if activity["species"] else None
    rising = [s["subject"] for s in trends["species"] if s["trend"] == "rising"]
    falling = [s["subject"] for s in trends["species"] if s["trend"] == "falling"]
    busiest_day = (
        max(trends["daily_totals"], key=lambda d: d["count"])["date"]
        if trends["daily_totals"]
        else None
    )

    headline = {
        "total_detections": activity["total_detections"],
        "total_encounters": encounters["total_encounters"],
        "distinct_subjects": activity["distinct_subjects"],
        "days_span": trends["days_span"],
        "top_subject": top_subject,
        "rising_subjects": rising,
        "falling_subjects": falling,
        "busiest_day": busiest_day,
        "richness": diversity["richness"],
        "evenness": diversity["evenness"],
        "total_alerts": alerts["total_alerts"],
        "alerts_suppressed": alerts["suppressed_total"],
    }

    return {
        "tz_offset_hours": tz_offset_hours,
        "headline": headline,
        "activity": activity,
        "trends": trends,
        "diversity": diversity,
        "encounters": encounters,
        "alerts": alerts,
    }
