"""Tests for review triage scoring (pure, import-isolated)."""

from clawcam_gateway.inference.triage import build_review_queue, review_priority


def _row(rid, label, conf, species=None, event=None):
    return {
        "result_id": rid, "event_id": event or rid,
        "top_label": label, "top_confidence": conf, "top_species": species,
    }


def test_confident_id_is_low_priority():
    v = review_priority(_row("r", "animal", 0.98, species="white-tailed deer"))
    assert v["priority"] == "low"
    assert v["score"] == 0.0


def test_borderline_confidence_is_high():
    v = review_priority(_row("r", "animal", 0.5, species="deer"))
    assert v["priority"] == "high"
    assert "borderline confidence" in v["reasons"]


def test_unidentified_animal_bumps_priority():
    v = review_priority(_row("r", "animal", 0.9, species=None))  # confident but no species
    assert v["priority"] == "medium"
    assert "unidentified species" in v["reasons"]


def test_rare_species_bumps_priority():
    v = review_priority(_row("r", "animal", 0.95, species="mountain lion"),
                        rare_species=["Mountain Lion"])
    assert "rare species: mountain lion" in v["reasons"]
    assert v["priority"] == "medium"  # 0.4 from rarity


def test_empty_detection_is_low():
    assert review_priority(_row("r", "", 0.0))["priority"] == "low"
    assert review_priority(_row("r", "empty", 0.0))["reasons"] == ["no detection"]


def test_very_low_confidence_flagged_but_not_high():
    v = review_priority(_row("r", "animal", 0.2, species="deer"))
    assert "very low confidence" in v["reasons"]
    assert v["priority"] == "low"  # 0.2 only


def test_queue_ranks_high_priority_first_and_counts():
    rows = [
        _row("a", "animal", 0.98, species="deer"),       # low
        _row("b", "animal", 0.5, species="fox"),         # high (borderline)
        _row("c", "animal", 0.9, species=None),          # medium (unidentified)
        _row("d", "empty", 0.0),                         # low
    ]
    q = build_review_queue(rows)
    assert q["total"] == 4
    assert q["counts"] == {"high": 1, "medium": 1, "low": 2}
    assert q["needs_review"] == 2
    # Ranked: high (b) then medium (c) then the two lows.
    assert [it["result_id"] for it in q["items"][:2]] == ["b", "c"]


def test_queue_tie_breaks_by_lower_confidence():
    # Two borderline (both score 0.6) → the less-confident one leads.
    rows = [_row("a", "animal", 0.6, species="deer"), _row("b", "animal", 0.45, species="fox")]
    q = build_review_queue(rows)
    assert [it["result_id"] for it in q["items"]] == ["b", "a"]
