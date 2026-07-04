"""Site report tests — pure composition of activity + trends + alert digest."""

from __future__ import annotations

import sys
from pathlib import Path

_GW = Path(__file__).parents[2] / "gateway"
if str(_GW) not in sys.path:
    sys.path.insert(0, str(_GW))

from clawcam_gateway.analytics.site import build_site_report


def _det(subject: str, day: int, hour: int = 22) -> dict:
    return {"top_species": subject, "ran_at": f"2026-05-{day:02d}T{hour:02d}:00:00Z"}


def test_empty_site_report():
    r = build_site_report([], [])
    assert r["headline"]["total_detections"] == 0
    assert r["headline"]["top_subject"] is None
    assert r["headline"]["total_alerts"] == 0
    # All three sub-reports are always present.
    assert set(r) >= {"headline", "activity", "trends", "alerts"}


def test_site_report_headline_and_composition():
    dets = [
        _det("deer", 11), _det("deer", 13), _det("deer", 14),
        _det("coyote", 14, hour=3),
    ]
    alert_events = [
        {"rule_name": "deer", "top_species": "deer", "top_label": "animal",
         "delivery_status": "delivered", "suppressed_count": 3},
    ]
    r = build_site_report(dets, alert_events, digest_window_label="7d")

    h = r["headline"]
    assert h["total_detections"] == 4
    assert h["distinct_subjects"] == 2
    assert h["top_subject"] == "deer"          # most detections
    assert h["busiest_day"] == "2026-05-14"     # two detections that day
    assert h["total_alerts"] == 1
    assert h["alerts_suppressed"] == 3
    assert h["richness"] == 2

    # The composed sub-reports carry through.
    assert r["activity"]["species"][0]["subject"] == "deer"
    assert r["trends"]["days_span"] == 3
    assert r["diversity"]["richness"] == 2
    assert r["alerts"]["window"] == "7d"


def test_rising_subject_surfaces_in_headline():
    dets = [_det("deer", d) for d in (11, 12)] + [_det("deer", d) for d in (13, 13, 14, 14, 14)]
    r = build_site_report(dets, [])
    assert "deer" in r["headline"]["rising_subjects"]
