"""Tests for the period-over-period comparison report (pure, import-isolated)."""

from clawcam_gateway.analytics import build_comparison_report


def _det(species):
    return {"top_species": species, "top_label": species, "top_confidence": 0.9}


def test_totals_and_pct_change():
    cur = [_det("deer")] * 6
    prev = [_det("deer")] * 4
    r = build_comparison_report(cur, prev)
    assert r["total_current"] == 6
    assert r["total_previous"] == 4
    assert r["total_delta"] == 2
    assert r["total_pct_change"] == 50.0


def test_new_and_dropped_subjects():
    cur = [_det("deer"), _det("fox")]
    prev = [_det("deer"), _det("bear")]
    r = build_comparison_report(cur, prev)
    assert r["new_subjects"] == ["fox"]
    assert r["dropped_subjects"] == ["bear"]


def test_per_subject_deltas_sorted_by_magnitude():
    cur = [_det("deer")] * 10 + [_det("fox")] * 1
    prev = [_det("deer")] * 2 + [_det("fox")] * 3
    r = build_comparison_report(cur, prev)
    # deer moved +8, fox moved -2 → deer ranks first.
    assert r["by_subject"][0]["subject"] == "deer"
    assert r["by_subject"][0]["delta"] == 8
    assert r["by_subject"][0]["direction"] == "up"
    fox = next(s for s in r["by_subject"] if s["subject"] == "fox")
    assert fox["delta"] == -2
    assert fox["direction"] == "down"


def test_pct_change_undefined_when_previous_zero():
    cur = [_det("fox")] * 3
    prev = []
    r = build_comparison_report(cur, prev)
    assert r["total_pct_change"] is None
    assert r["new_subjects"] == ["fox"]
    fox = r["by_subject"][0]
    assert fox["pct_change"] is None


def test_dominant_subject_change_flagged():
    cur = [_det("fox")] * 5 + [_det("deer")] * 1
    prev = [_det("deer")] * 5 + [_det("fox")] * 1
    r = build_comparison_report(cur, prev)
    assert r["dominant_changed"] is True
    assert r["dominant_previous"] == "deer"
    assert r["dominant_current"] == "fox"
    assert "dominant deer→fox" in r["headline"]


def test_richness_delta():
    cur = [_det("deer"), _det("fox"), _det("bear")]
    prev = [_det("deer")]
    r = build_comparison_report(cur, prev)
    assert r["richness_current"] == 3
    assert r["richness_previous"] == 1
    assert r["richness_delta"] == 2
