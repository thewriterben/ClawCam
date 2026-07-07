"""Tests for the single-subject species profile (pure composition)."""

from clawcam_gateway.analytics.species import build_species_profile


def _d(subject, date, hour=22):
    return {"top_species": subject, "top_label": subject,
            "ran_at": f"{date}T{hour:02d}:00:00+00:00"}


def test_absent_subject_is_not_found():
    rows = [_d("deer", "2026-05-01")]
    p = build_species_profile(rows, "wolf")
    assert p["found"] is False
    assert p["count"] == 0
    assert p["rai"] is None
    assert p["top_cooccurring"] == []


def test_profile_core_fields():
    # deer nightly for 10 days (nocturnal); fox alongside deer on the same nights.
    rows = []
    for day in range(1, 11):
        rows.append(_d("deer", f"2026-05-{day:02d}", hour=23))
        rows.append(_d("fox", f"2026-05-{day:02d}", hour=23))
    rows.append(_d("hawk", "2026-05-05", hour=12))  # unrelated daytime species

    p = build_species_profile(rows, "deer")
    assert p["found"] is True
    assert p["count"] == 10
    assert p["diel_pattern"] == "nocturnal"
    assert p["rai"] is not None
    assert 0 < p["share_of_detections"] < 100
    assert p["total_encounters"] >= 1
    # fox shares every night window with deer → it's the top co-occurring partner.
    assert p["top_cooccurring"][0]["partner"] == "fox"
    assert p["top_cooccurring"][0]["jaccard"] == 1.0


def test_max_partners_caps_the_list():
    rows = []
    for day in range(1, 6):
        for sp in ("deer", "fox", "coyote", "bobcat"):
            rows.append(_d(sp, f"2026-05-{day:02d}", hour=23))
    p = build_species_profile(rows, "deer", max_partners=2)
    assert len(p["top_cooccurring"]) == 2


def test_share_of_detections():
    rows = [_d("deer", "2026-05-01")] * 3 + [_d("fox", "2026-05-01")]
    p = build_species_profile(rows, "deer")
    assert p["count"] == 3
    assert p["share_of_detections"] == 75.0
