"""Tests for the daily site section (pure, import-isolated).

Imports only ``clawcam_gateway.analytics`` — no DB, no framework — so it runs in the
sandbox despite the flaky mount that truncates ``database.py``.
"""

from clawcam_gateway.analytics import build_daily_site_section


def _det(species, ran_at):
    return {"top_species": species, "top_label": species, "top_confidence": 0.9, "ran_at": ran_at}


def test_empty_day_reports_no_detections():
    out = build_daily_site_section([])
    assert out["sentence"] == "No animal detections recorded."
    assert out["report"]["headline"]["total_detections"] == 0
    # Digest window label threads through to the alert digest.
    assert out["report"]["alerts"]["window"] == "1d"


def test_sentence_names_totals_and_top_subject():
    dets = [
        _det("deer", "2026-07-01T22:00:00"),
        _det("deer", "2026-07-01T23:00:00"),
        _det("fox", "2026-07-01T02:00:00"),
    ]
    out = build_daily_site_section(dets)
    s = out["sentence"]
    assert "3 detections" in s
    assert "2 subject(s)" in s
    assert "led by deer" in s  # deer is the most-detected subject
    assert out["report"]["headline"]["total_detections"] == 3
    assert out["report"]["headline"]["distinct_subjects"] == 2


def test_report_carries_all_four_subreports():
    dets = [_det("deer", "2026-07-01T22:00:00"), _det("fox", "2026-07-01T02:00:00")]
    report = build_daily_site_section(dets)["report"]
    assert set(("activity", "trends", "diversity", "alerts")).issubset(report)
    assert report["diversity"]["richness"] == 2


def test_alerts_fold_into_sentence():
    dets = [_det("deer", "2026-07-01T22:00:00")]
    events = [
        {
            "rule_id": "r1",
            "rule_name": "night deer",
            "severity": "warning",
            "top_species": "deer",
            "delivery_status": "delivered",
            "suppressed_count": 2,
            "fired_at": "2026-07-01T22:00:05",
        }
    ]
    out = build_daily_site_section(dets, alert_events=events)
    assert "1 alert(s)" in out["sentence"]
    assert "2 suppressed" in out["sentence"]
    assert out["report"]["headline"]["total_alerts"] == 1
    assert out["report"]["headline"]["alerts_suppressed"] == 2
