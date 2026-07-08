"""Tests for the habitat use-vs-availability report (pure, G7)."""

from clawcam_gateway.analytics.habitat import LandCover, build_habitat_report


# A 2×2 land-cover grid at ~10 m spacing: half forest, half grassland.
def _lc():
    return LandCover(
        origin_lat=45.5, origin_lon=-122.6, step=0.001,
        rows=[
            ["forest", "grassland"],
            ["forest", "grassland"],
        ],
    )


def _det(subject, lat, lon):
    return {"top_species": subject, "latitude": lat, "longitude": lon}


def test_classify_and_availability():
    lc = _lc()
    assert lc.classify(45.5, -122.6) == "forest"        # cell (0,0)
    assert lc.classify(45.5, -122.599) == "grassland"   # cell (0,1)
    assert lc.classify(10.0, 10.0) is None              # off-grid
    assert dict(lc.availability()) == {"forest": 2, "grassland": 2}


def test_preference_shows_in_selection_ratio_and_electivity():
    lc = _lc()
    # Deer detected only in forest cells → forest used, grassland avoided.
    dets = [_det("deer", 45.5, -122.6), _det("deer", 45.501, -122.6),
            _det("deer", 45.5, -122.6)]
    r = build_habitat_report(dets, lc)
    by = {c["class"]: c for c in r["classes"]}
    assert r["located"] == 3
    # forest: use_fraction 1.0, availability 0.5 → ratio 2.0, electivity +0.333
    assert by["forest"]["use"] == 3
    assert by["forest"]["selection_ratio"] == 2.0
    assert by["forest"]["electivity"] > 0
    # grassland: unused → ratio 0, electivity -1
    assert by["grassland"]["use"] == 0
    assert by["grassland"]["selection_ratio"] == 0.0
    assert by["grassland"]["electivity"] == -1.0


def test_no_preference_when_use_matches_availability():
    lc = _lc()
    dets = [_det("deer", 45.5, -122.6), _det("deer", 45.5, -122.599)]  # one each
    by = {c["class"]: c for c in build_habitat_report(dets, lc)["classes"]}
    assert by["forest"]["selection_ratio"] == 1.0
    assert by["forest"]["electivity"] == 0.0
    assert by["grassland"]["selection_ratio"] == 1.0


def test_unlocated_and_offgrid_counted_separately():
    lc = _lc()
    dets = [
        _det("deer", 45.5, -122.6),          # located, forest
        {"top_species": "fox"},              # no location
        _det("owl", 10.0, 10.0),             # off-grid
    ]
    r = build_habitat_report(dets, lc)
    assert r["located"] == 1
    assert r["unlocated"] == 2


def test_top_species_per_class():
    lc = _lc()
    dets = [_det("deer", 45.5, -122.6)] * 3 + [_det("fox", 45.501, -122.6)]
    by = {c["class"]: c for c in build_habitat_report(dets, lc)["classes"]}
    assert by["forest"]["top_species"][0] == ("deer", 3)
