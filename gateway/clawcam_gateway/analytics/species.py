"""Species profile — one drill-down card for a single subject.

The suite answers site-wide questions; this answers "tell me everything about *this*
species here." It composes the existing pure builders and pulls out just the target
subject: its abundance (RAI over the whole survey's effort), diel activity pattern and
peak hour, trend direction, independent-encounter count, first/last seen, share of all
detections, and the species it most often shows up alongside.

Pure and storage-agnostic: it takes the full detection list (needed so RAI effort and
co-occurrence partners are computed against the whole survey) plus the subject name, and
composes ``activity``, ``abundance``, ``trends``, ``encounters``, and ``cooccurrence``.
No DB or framework imports.
"""

from __future__ import annotations

from typing import Any

from .abundance import build_abundance_report
from .activity import build_activity_report
from .cooccurrence import build_cooccurrence_report
from .encounters import build_encounter_report
from .trends import build_trend_report


def _subject(det: dict[str, Any]) -> str | None:
    return det.get("top_species") or det.get("top_label")


def build_species_profile(
    detections: list[dict[str, Any]],
    subject: str,
    tz_offset_hours: int = 0,
    encounter_gap_minutes: int = 30,
    cooccurrence_window_minutes: int = 60,
    max_partners: int = 3,
) -> dict[str, Any]:
    """Compose a single-subject profile from the whole detection set.

    Args:
        detections:      The full detection list (all subjects) — RAI effort and
                         co-occurrence partners are computed against the whole survey.
        subject:         The species/label to profile.
        tz_offset_hours: Local-time shift for activity/abundance bucketing.
        encounter_gap_minutes:      Gap separating independent encounters.
        cooccurrence_window_minutes: Window width for finding co-occurring partners.
        max_partners:    How many top co-occurring partners to return.

    Returns ``{subject, found, count, share_of_detections, rai, diel_pattern, peak_hour,
    first_seen, last_seen, trend, total_encounters, top_cooccurring}``. When the subject
    has no detections, ``found`` is ``False`` and the numeric fields are zero/None.
    """
    subject_rows = [d for d in detections if _subject(d) == subject]
    total_detections = sum(1 for d in detections if _subject(d))
    count = len(subject_rows)
    if count == 0:
        return {
            "subject": subject, "found": False, "count": 0,
            "share_of_detections": 0.0, "rai": None, "diel_pattern": None,
            "peak_hour": None, "first_seen": None, "last_seen": None,
            "trend": None, "total_encounters": 0, "top_cooccurring": [],
        }

    activity = build_activity_report(subject_rows, tz_offset_hours=tz_offset_hours)
    act = activity["species"][0] if activity["species"] else {}

    abundance = build_abundance_report(detections, tz_offset_hours=tz_offset_hours)
    rai = next((s["rai"] for s in abundance["species"] if s["subject"] == subject), None)

    trends = build_trend_report(subject_rows, tz_offset_hours=tz_offset_hours)
    trend = trends["species"][0]["trend"] if trends["species"] else None

    encounters = build_encounter_report(subject_rows, gap_minutes=encounter_gap_minutes)

    cooc = build_cooccurrence_report(
        detections, window_minutes=cooccurrence_window_minutes, tz_offset_hours=tz_offset_hours
    )
    partners: list[dict[str, Any]] = []
    for pair in cooc["pairs"]:
        if pair["a"] == subject or pair["b"] == subject:
            partner = pair["b"] if pair["a"] == subject else pair["a"]
            partners.append({
                "partner": partner,
                "shared_windows": pair["shared_windows"],
                "jaccard": pair["jaccard"],
                "activity_overlap": pair["activity_overlap"],
            })
    partners.sort(key=lambda p: (-p["jaccard"], -p["activity_overlap"], p["partner"]))

    return {
        "subject": subject,
        "found": True,
        "count": count,
        "share_of_detections": round(count / total_detections * 100.0, 1) if total_detections else 0.0,
        "rai": rai,
        "diel_pattern": act.get("diel_pattern"),
        "peak_hour": act.get("peak_hour"),
        "first_seen": act.get("first_seen"),
        "last_seen": act.get("last_seen"),
        "trend": trend,
        "total_encounters": encounters["total_encounters"],
        "top_cooccurring": partners[:max(0, int(max_partners))],
    }
