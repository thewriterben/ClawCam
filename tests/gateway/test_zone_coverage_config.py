"""Config wiring for the detection-zone coverage-matching knob.

`CLAWCAM_ALERT_ZONE_MIN_COVERAGE` → GatewayConfig.alert_zone_min_coverage, which the
app threads into the AlertEvaluator (default None = center-point matching, unchanged).
"""

from clawcam_gateway.config import GatewayConfig


def test_zone_min_coverage_defaults_to_none(monkeypatch):
    monkeypatch.delenv("CLAWCAM_ALERT_ZONE_MIN_COVERAGE", raising=False)
    assert GatewayConfig.from_env().alert_zone_min_coverage is None


def test_zone_min_coverage_parses_a_float(monkeypatch):
    monkeypatch.setenv("CLAWCAM_ALERT_ZONE_MIN_COVERAGE", "0.4")
    assert GatewayConfig.from_env().alert_zone_min_coverage == 0.4


def test_empty_env_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("CLAWCAM_ALERT_ZONE_MIN_COVERAGE", "")
    assert GatewayConfig.from_env().alert_zone_min_coverage is None


def test_evaluator_accepts_and_stores_zone_min_coverage():
    # Plumbing check: the AlertEvaluator constructor takes the knob and holds it, so the
    # zone-filtering call can pass it to apply_zones_to_result.
    from clawcam_gateway.alerts.evaluator import AlertEvaluator

    ev = AlertEvaluator(db=None, zone_min_coverage=0.5)
    assert ev._zone_min_coverage == 0.5
    assert AlertEvaluator(db=None)._zone_min_coverage is None
