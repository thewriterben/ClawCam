"""Alert polish tests — rule severity, minimum-severity delivery gate, de-duplication.

Mirrors the Oh-Ben-Claw notification work (severity routing + de-dup) on ClawCam's
alert engine. A camera trap sees the same animal many times a minute; de-dup collapses
those repeats, and the severity gate lets an operator record everything but only push the
loud stuff.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
if str(_GW) not in sys.path:
    sys.path.insert(0, str(_GW))

from clawcam_gateway.alerts.evaluator import AlertEvaluator
from clawcam_gateway.alerts.rules import severity_rank
from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.storage.database import GatewayDatabase


def _seed(tmp_path: Path) -> GatewayDatabase:
    """A DB with one device + event + a deer detection to evaluate against."""
    db = GatewayDatabase(tmp_path / "sev.db")
    db.upsert_device({
        "device_id": "d1", "device_type": "node", "name": "n", "status": "active",
        "created_at": "2026-05-14T00:00:00Z", "last_seen_at": "2026-05-14T00:00:00Z",
        "hardware": "test", "firmware_version": "1.0.0",
        "capabilities": ["cap_clawcam_camera_trap"],
    })
    db.add_event({
        "event_id": "e1", "event_type": "motion_detected", "device_id": "d1",
        "timestamp": "2026-05-14T10:00:00Z", "time_source": "gps", "source": "node",
        "media": [], "metadata": {},
    })
    result = InferenceResult(
        model_name="mock", model_version="1.0.0",
        detections=[Detection("animal", 0.91, [0, 0, 1, 1], "Odocoileus virginianus")],
    )
    db.save_inference_result("e1", "/media/e1.jpg", result)
    return db


def _add_rule(db: GatewayDatabase, severity: str = "warning", webhook_url=None) -> None:
    db.add_alert_rule({
        "rule_id": "rule-1", "name": "deer", "label": "animal",
        "min_confidence": 0.5, "webhook_url": webhook_url, "enabled": True,
        "severity": severity,
    })


def test_severity_rank_orders_levels():
    assert severity_rank("info") < severity_rank("warning") < severity_rank("critical")
    assert severity_rank(None) == severity_rank("warning")
    assert severity_rank("bogus") == severity_rank("warning")


def test_rule_severity_persists(tmp_path):
    db = _seed(tmp_path)
    _add_rule(db, severity="critical")
    assert db.get_alert_rule("rule-1")["severity"] == "critical"
    assert db.list_alert_rules()[0]["severity"] == "critical"


def test_below_min_severity_records_but_skips_webhook(tmp_path):
    db = _seed(tmp_path)
    _add_rule(db, severity="warning", webhook_url="http://example.invalid/hook")
    ev = AlertEvaluator(db=db, min_severity="critical")
    fired = ev.evaluate("e1", device_id="d1")
    assert fired == 1  # the rule still matched (and was recorded)
    events = db.list_alert_events()
    assert len(events) == 1
    assert events[0]["delivery_status"] == "skipped_severity"
    assert events[0]["severity"] == "warning"


def test_at_or_above_min_severity_is_not_skipped(tmp_path):
    db = _seed(tmp_path)
    _add_rule(db, severity="critical", webhook_url=None)  # no url → 'failed', not skipped
    ev = AlertEvaluator(db=db, min_severity="critical")
    ev.evaluate("e1", device_id="d1")
    events = db.list_alert_events()
    assert len(events) == 1
    assert events[0]["delivery_status"] != "skipped_severity"


def test_dedup_collapses_repeats(tmp_path):
    db = _seed(tmp_path)
    _add_rule(db, severity="warning")
    ev = AlertEvaluator(db=db, dedup_window_s=3600)
    ev.evaluate("e1", device_id="d1")
    ev.evaluate("e1", device_id="d1")  # identical within the window → collapsed
    events = db.list_alert_events()
    assert len(events) == 1, "the repeat is rolled onto the first alert, not a new row"
    assert events[0]["suppressed_count"] == 1


def test_dedup_off_by_default(tmp_path):
    db = _seed(tmp_path)
    _add_rule(db, severity="warning")
    ev = AlertEvaluator(db=db)  # dedup_window_s = 0
    ev.evaluate("e1", device_id="d1")
    ev.evaluate("e1", device_id="d1")
    assert len(db.list_alert_events()) == 2
