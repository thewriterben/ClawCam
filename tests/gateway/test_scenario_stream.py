"""Tests for the deterministic scenario detection-stream generator (pure)."""

from collections import Counter

from clawcam_gateway.simulator.scenario import (
    ScenarioSpec,
    SpeciesProfile,
    build_detection_stream,
)


def _hour(row):
    # ran_at is "YYYY-MM-DDTHH:MM:SS+00:00"
    return int(row["ran_at"][11:13])


def test_deterministic_for_a_seed():
    spec = ScenarioSpec(species=[SpeciesProfile("deer", daily_rate=6)], days=5, seed=42)
    a = build_detection_stream(spec)
    b = build_detection_stream(spec)
    assert a == b  # same seed → identical stream


def test_different_seed_differs():
    s1 = ScenarioSpec(species=[SpeciesProfile("deer", daily_rate=6)], days=5, seed=1)
    s2 = ScenarioSpec(species=[SpeciesProfile("deer", daily_rate=6)], days=5, seed=2)
    assert build_detection_stream(s1) != build_detection_stream(s2)


def test_rows_have_analytics_shape_and_are_time_sorted():
    spec = ScenarioSpec(species=[SpeciesProfile("deer", daily_rate=8)], days=3, seed=7)
    rows = build_detection_stream(spec)
    assert rows, "expected some detections"
    for r in rows:
        assert set(r) >= {"top_species", "top_label", "top_confidence", "ran_at", "review_state"}
        assert 0.0 < r["top_confidence"] <= 1.0
    assert [r["ran_at"] for r in rows] == sorted(r["ran_at"] for r in rows)


def test_nocturnal_species_is_mostly_at_night():
    spec = ScenarioSpec(
        species=[SpeciesProfile("owl", daily_rate=40, diel="nocturnal")],
        days=10, seed=3,
    )
    rows = build_detection_stream(spec)
    night = sum(1 for r in rows if _hour(r) >= 20 or _hour(r) < 5)
    assert night / len(rows) > 0.55  # clearly night-weighted


def test_diurnal_species_is_mostly_by_day():
    spec = ScenarioSpec(
        species=[SpeciesProfile("hawk", daily_rate=40, diel="diurnal")],
        days=10, seed=4,
    )
    rows = build_detection_stream(spec)
    day = sum(1 for r in rows if 8 <= _hour(r) < 17)
    assert day / len(rows) > 0.45


def test_drop_day_is_empty_and_spike_day_is_busy():
    spec = ScenarioSpec(
        species=[SpeciesProfile("deer", daily_rate=10)],
        days=5, seed=9, drop_days=[2], spike_days=[4],
    )
    rows = build_detection_stream(spec)
    per_day = Counter(r["ran_at"][:10] for r in rows)
    days = sorted(per_day) if per_day else []
    # Day index 2 (2026-05-03) should have zero detections.
    assert "2026-05-03" not in per_day
    # The spike day should out-count a normal day comfortably.
    normal = per_day.get("2026-05-01", 0)
    spike = per_day.get("2026-05-05", 0)
    assert spike > normal


def test_multi_species_all_present():
    spec = ScenarioSpec(
        species=[
            SpeciesProfile("deer", daily_rate=8, diel="crepuscular"),
            SpeciesProfile("fox", daily_rate=5, diel="nocturnal"),
        ],
        days=6, seed=11,
    )
    rows = build_detection_stream(spec)
    subjects = {r["top_species"] for r in rows}
    assert subjects == {"deer", "fox"}
