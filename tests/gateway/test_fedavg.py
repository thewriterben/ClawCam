"""Tests for federated averaging (pure, G9)."""

import pytest

from clawcam_gateway.federated.fedavg import federated_average


def _u(node_id, n, **weights):
    return {"node_id": node_id, "sample_count": n, "weights": weights}


def test_equal_samples_is_plain_mean():
    r = federated_average([
        _u("a", 10, w=[0.0, 0.0]),
        _u("b", 10, w=[10.0, 20.0]),
    ])
    assert r["weights"]["w"] == [5.0, 10.0]
    assert r["total_weight"] == 20.0
    assert r["nodes"] == ["a", "b"]
    assert r["params"] == ["w"]


def test_sample_weighting_favors_larger_node():
    # a: 30 samples at 0, b: 10 samples at 40 → (30*0 + 10*40)/40 = 10.
    r = federated_average([_u("a", 30, w=[0.0]), _u("b", 10, w=[40.0])])
    assert r["weights"]["w"] == [10.0]


def test_trust_downweights_a_node():
    # Same as above but a's trust is 0.0 → only b contributes.
    r = federated_average([_u("a", 30, w=[0.0]), _u("b", 10, w=[40.0])], trust={"a": 0.0})
    assert r["weights"]["w"] == [40.0]
    assert r["nodes"] == ["b"]


def test_zero_sample_node_skipped():
    r = federated_average([_u("a", 0, w=[99.0]), _u("b", 5, w=[2.0])])
    assert r["weights"]["w"] == [2.0]
    assert r["nodes"] == ["b"]


def test_single_node_returns_its_weights():
    r = federated_average([_u("solo", 7, w=[1.0, 2.0, 3.0])])
    assert r["weights"]["w"] == [1.0, 2.0, 3.0]


def test_multi_param_models():
    r = federated_average([
        _u("a", 1, head=[2.0], bias=[0.0, 0.0]),
        _u("b", 1, head=[4.0], bias=[10.0, 20.0]),
    ])
    assert r["weights"]["head"] == [3.0]
    assert r["weights"]["bias"] == [5.0, 10.0]
    assert set(r["params"]) == {"head", "bias"}


def test_param_name_mismatch_raises():
    with pytest.raises(ValueError):
        federated_average([_u("a", 1, w=[1.0]), _u("b", 1, x=[1.0])])


def test_param_length_mismatch_raises():
    with pytest.raises(ValueError):
        federated_average([_u("a", 1, w=[1.0, 2.0]), _u("b", 1, w=[1.0])])


def test_empty_and_zero_weight_raise():
    with pytest.raises(ValueError):
        federated_average([])
    with pytest.raises(ValueError):
        federated_average([_u("a", 0, w=[1.0])])  # no effective weight
