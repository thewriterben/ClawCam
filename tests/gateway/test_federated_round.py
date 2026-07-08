"""Tests for the federated round loop (pure, G9)."""

import pytest

from clawcam_gateway.federated.round import (
    build_local_update,
    federated_round_from_reviews,
    run_federated_round,
)


def _rev(conf, state):
    return {"top_confidence": conf, "review_state": state}


def test_local_update_from_reviews():
    # Clean node: high-confidence verified, one low rejected → a real threshold, 4 samples.
    rows = [
        _rev(0.95, "verified"), _rev(0.85, "verified"),
        _rev(0.70, "rejected"), _rev(0.60, "corrected"),
    ]
    u = build_local_update("north", rows, target_precision=0.9)
    assert u["node_id"] == "north"
    assert u["sample_count"] == 4
    t = u["weights"]["threshold"][0]
    assert 0.0 < t <= 1.0


def test_local_update_unmet_precision_falls_back_conservative():
    # All rejected → no threshold meets precision → conservative 1.0.
    rows = [_rev(0.9, "rejected"), _rev(0.8, "rejected")]
    u = build_local_update("noisy", rows)
    assert u["weights"]["threshold"] == [1.0]
    assert u["sample_count"] == 2


def test_run_round_versions_and_aggregates():
    updates = [
        {"node_id": "a", "sample_count": 10, "weights": {"threshold": [0.5]}},
        {"node_id": "b", "sample_count": 10, "weights": {"threshold": [0.7]}},
    ]
    r = run_federated_round(updates)
    assert r["version"] == 1
    assert r["weights"]["threshold"] == [0.6]  # equal samples → mean
    # Passing the prior model bumps the version.
    r2 = run_federated_round(updates, previous=r)
    assert r2["version"] == 2


def test_trust_downweights_in_round():
    updates = [
        {"node_id": "good", "sample_count": 10, "weights": {"threshold": [0.5]}},
        {"node_id": "drift", "sample_count": 10, "weights": {"threshold": [0.9]}},
    ]
    r = run_federated_round(updates, trust={"drift": 0.0})
    assert r["weights"]["threshold"] == [0.5]
    assert r["nodes"] == ["good"]


def test_end_to_end_from_reviews():
    node_reviews = {
        "north": [_rev(0.9, "verified"), _rev(0.8, "verified"), _rev(0.5, "rejected")],
        "ridge": [_rev(0.95, "verified"), _rev(0.6, "rejected")],
    }
    g = federated_round_from_reviews(node_reviews, target_precision=0.9)
    assert g["version"] == 1
    assert set(g["nodes"]) == {"north", "ridge"}
    assert "threshold" in g["weights"] and len(g["weights"]["threshold"]) == 1


def test_all_empty_reviews_raise():
    with pytest.raises(ValueError):
        federated_round_from_reviews({"a": [], "b": []})
