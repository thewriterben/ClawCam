"""Tests for encounter sessionization (pure, import-isolated)."""

from clawcam_gateway.analytics.encounters import build_encounter_report


def _det(species, ran_at):
    return {"top_species": species, "top_label": species, "top_confidence": 0.9, "ran_at": ran_at}


def test_lingering_burst_is_one_encounter():
    # Five deer frames within a couple of minutes → one encounter.
    dets = [
        _det("deer", "2026-07-01T22:00:00"),
        _det("deer", "2026-07-01T22:00:30"),
        _det("deer", "2026-07-01T22:01:00"),
        _det("deer", "2026-07-01T22:01:40"),
        _det("deer", "2026-07-01T22:02:00"),
    ]
    r = build_encounter_report(dets, gap_minutes=30)
    assert r["total_detections"] == 5
    assert r["total_encounters"] == 1
    assert r["by_subject"]["deer"]["encounters"] == 1
    assert r["by_subject"]["deer"]["compression"] == 5.0
    enc = r["encounters"][0]
    assert enc["detections"] == 5
    assert enc["duration_s"] == 120


def test_gap_starts_a_new_encounter():
    dets = [
        _det("deer", "2026-07-01T22:00:00"),
        _det("deer", "2026-07-01T22:05:00"),   # within 30 min → same encounter
        _det("deer", "2026-07-01T23:30:00"),   # 85 min later → new encounter
    ]
    r = build_encounter_report(dets, gap_minutes=30)
    assert r["total_encounters"] == 2
    assert r["by_subject"]["deer"]["encounters"] == 2
    assert r["by_subject"]["deer"]["detections"] == 3


def test_subjects_are_independent():
    dets = [
        _det("deer", "2026-07-01T22:00:00"),
        _det("fox", "2026-07-01T22:00:10"),   # different subject, overlapping in time
        _det("deer", "2026-07-01T22:00:20"),
    ]
    r = build_encounter_report(dets, gap_minutes=30)
    assert r["total_encounters"] == 2  # one deer encounter, one fox encounter
    assert r["by_subject"]["deer"]["encounters"] == 1
    assert r["by_subject"]["fox"]["encounters"] == 1


def test_encounters_sorted_by_start_across_subjects():
    dets = [
        _det("fox", "2026-07-01T23:00:00"),
        _det("deer", "2026-07-01T06:00:00"),
    ]
    r = build_encounter_report(dets, gap_minutes=30)
    starts = [e["subject"] for e in r["encounters"]]
    assert starts == ["deer", "fox"]  # earliest-first


def test_bad_timestamps_are_ignored():
    dets = [
        _det("deer", "2026-07-01T22:00:00"),
        _det("deer", "not-a-date"),
        _det("deer", None),
    ]
    r = build_encounter_report(dets, gap_minutes=30)
    assert r["ignored_no_timestamp"] == 2
    assert r["total_detections"] == 1
    assert r["total_encounters"] == 1


def test_empty_is_empty():
    r = build_encounter_report([], gap_minutes=30)
    assert r["total_encounters"] == 0
    assert r["total_detections"] == 0
    assert r["by_subject"] == {}
    assert r["encounters"] == []
