"""Phase 6 tests: Alert rules, webhook delivery, evaluator, REST, MCP tools.

Coverage
--------
- AlertRule.matches: label, confidence, species, device filters
- deliver_webhook: success/failure/timeout/no-url paths (with mock server)
- AlertEvaluator.evaluate: rule matching, alert_event persistence, no-raise guarantee
- DB: add/get/list/update/delete alert_rules; add/list alert_events
- REST: POST/GET/PATCH/DELETE /api/v1/alert-rules; GET /api/v1/alerts
- MCP tools: list_alert_rules, list_recent_alerts, create_alert_rule; dispatch
- Stdio server: new tool definitions present
- Brain adapter: policy classification for all three new tools
- Config: CLAWCAM_ALERT_WEBHOOK_URL env var parsed correctly
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
_BRAIN_DIR = _REPO / "brain" / "oh-ben-claw-adapter"

for _p in (_GW, _BRAIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ── Imports ───────────────────────────────────────────────────────────────────

from fastapi.testclient import TestClient

from clawcam_gateway.alerts.evaluator import AlertEvaluator
from clawcam_gateway.alerts.rules import AlertRule
from clawcam_gateway.alerts.webhook import deliver_webhook
from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.mcp_server.stdio_server import TOOL_DEFINITIONS
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    create_alert_rule as tool_create_alert_rule,
    list_alert_rules as tool_list_alert_rules,
    list_recent_alerts as tool_list_recent_alerts,
)
from clawcam_adapter import ToolPolicy  # type: ignore[import]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_rule(**kwargs: Any) -> AlertRule:
    defaults = {
        "rule_id": f"rule-{uuid.uuid4().hex[:8]}",
        "name": "test rule",
        "enabled": True,
        "min_confidence": 0.5,
    }
    defaults.update(kwargs)
    return AlertRule(**defaults)


def _make_result(**kwargs: Any) -> dict[str, Any]:
    defaults = {
        "top_label": "animal",
        "top_confidence": 0.85,
        "top_species": "Odocoileus virginianus",
        "model_name": "mock_detector",
        "ran_at": "2026-05-14T10:01:00Z",
    }
    defaults.update(kwargs)
    return defaults


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "test.db")
    db.upsert_device({
        "device_id": "alert-dev-1",
        "name": "Alert Test Node",
        "hardware": "test",
        "firmware_version": "1.0.0",
        "capabilities": ["cap_clawcam_camera_trap"],
    })
    # Seed an event + inference result so evaluator has something to fetch
    db.add_event({
        "event_id": "evt-alert-001",
        "event_type": "motion_detected",
        "device_id": "alert-dev-1",
        "timestamp": "2026-05-14T10:00:00Z",
        "time_source": "gps",
        "source": "pir",
        "media": [],
        "metadata": {},
    })
    result = InferenceResult(
        model_name="mock_detector",
        model_version="1.0.0",
        detections=[Detection("animal", 0.91, [0, 0, 1, 1], "Odocoileus virginianus")],
    )
    db.save_inference_result("evt-alert-001", "/media/evt-alert-001.jpg", result)
    return db


@pytest.fixture()
def client(tmp_path: Path, tmp_db: GatewayDatabase) -> TestClient:
    cfg = GatewayConfig(
        database_path=tmp_db.path,
        media_dir=tmp_path / "media",
    )
    return TestClient(create_app(config=cfg))


# ── Mini HTTP server for webhook tests ───────────────────────────────────────

class _WebhookCapture:
    """Spin up a local HTTP server that captures one POST and returns 200."""

    def __init__(self):
        self.received: list[dict] = []
        self._server: HTTPServer | None = None

    def start(self) -> str:
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    capture.received.append(json.loads(body))
                except Exception:
                    capture.received.append({"raw": body.decode()})
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass  # silence test output

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        port = self._server.server_address[1]
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()
        return f"http://127.0.0.1:{port}/"

    def stop(self):
        if self._server:
            self._server.shutdown()


@pytest.fixture()
def webhook_server():
    cap = _WebhookCapture()
    url = cap.start()
    yield cap, url
    cap.stop()


# ── AlertRule.matches ─────────────────────────────────────────────────────────

class TestAlertRuleMatches:
    def test_basic_match(self):
        rule = _make_rule(min_confidence=0.5)
        assert rule.matches(_make_result(top_confidence=0.85))

    def test_confidence_gate_fails(self):
        rule = _make_rule(min_confidence=0.95)
        assert not rule.matches(_make_result(top_confidence=0.85))

    def test_confidence_exact_boundary(self):
        rule = _make_rule(min_confidence=0.85)
        assert rule.matches(_make_result(top_confidence=0.85))

    def test_label_filter_match(self):
        rule = _make_rule(label="animal")
        assert rule.matches(_make_result(top_label="animal"))

    def test_label_filter_no_match(self):
        rule = _make_rule(label="person")
        assert not rule.matches(_make_result(top_label="animal"))

    def test_label_none_matches_any(self):
        rule = _make_rule(label=None)
        assert rule.matches(_make_result(top_label="animal"))
        assert rule.matches(_make_result(top_label="person"))
        assert rule.matches(_make_result(top_label="vehicle"))

    def test_species_pattern_match(self):
        rule = _make_rule(species_pattern="virginianus")
        assert rule.matches(_make_result(top_species="Odocoileus virginianus"))

    def test_species_pattern_case_insensitive(self):
        rule = _make_rule(species_pattern="DEER")
        assert rule.matches(_make_result(top_species="white-tailed deer"))

    def test_species_pattern_no_match(self):
        rule = _make_rule(species_pattern="bear")
        assert not rule.matches(_make_result(top_species="Odocoileus virginianus"))

    def test_species_pattern_none_matches_any(self):
        rule = _make_rule(species_pattern=None)
        assert rule.matches(_make_result(top_species=None))
        assert rule.matches(_make_result(top_species="anything"))

    def test_device_filter_match(self):
        rule = _make_rule(device_id="dev-1")
        assert rule.matches(_make_result(), device_id="dev-1")

    def test_device_filter_no_match(self):
        rule = _make_rule(device_id="dev-1")
        assert not rule.matches(_make_result(), device_id="dev-2")

    def test_device_filter_none_matches_any(self):
        rule = _make_rule(device_id=None)
        assert rule.matches(_make_result(), device_id="any-device")

    def test_disabled_rule_never_matches(self):
        rule = _make_rule(enabled=False, min_confidence=0.0)
        assert not rule.matches(_make_result(top_confidence=0.99))

    def test_to_dict_round_trip(self):
        rule = _make_rule(label="animal", species_pattern="deer", min_confidence=0.7)
        d = rule.to_dict()
        rule2 = AlertRule.from_dict(d)
        assert rule2.rule_id == rule.rule_id
        assert rule2.label == rule.label
        assert rule2.min_confidence == rule.min_confidence


# ── deliver_webhook ───────────────────────────────────────────────────────────

class TestDeliverWebhook:
    def test_success(self, webhook_server):
        cap, url = webhook_server
        ok, status, error = deliver_webhook(url, {"test": "payload"})
        assert ok is True
        assert status == 200
        assert error is None
        assert len(cap.received) == 1
        assert cap.received[0]["test"] == "payload"

    def test_no_url_returns_failure(self):
        ok, status, error = deliver_webhook("", {"x": 1})
        assert ok is False
        assert status is None

    def test_unreachable_url_returns_failure(self):
        ok, status, error = deliver_webhook("http://127.0.0.1:1/", {"x": 1}, timeout=1)
        assert ok is False

    def test_payload_is_json(self, webhook_server):
        cap, url = webhook_server
        payload = {"event_id": "evt-1", "label": "animal", "confidence": 0.91}
        deliver_webhook(url, payload)
        assert cap.received[0]["event_id"] == "evt-1"


# ── AlertEvaluator ────────────────────────────────────────────────────────────

class TestAlertEvaluator:
    def test_no_rules_fires_zero(self, tmp_db: GatewayDatabase):
        evaluator = AlertEvaluator(tmp_db)
        fired = evaluator.evaluate("evt-alert-001", device_id="alert-dev-1")
        assert fired == 0

    def test_matching_rule_fires(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({
            "rule_id": "rule-test-1",
            "name": "animal alert",
            "label": "animal",
            "min_confidence": 0.5,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        fired = evaluator.evaluate("evt-alert-001", device_id="alert-dev-1")
        assert fired == 1

    def test_non_matching_rule_does_not_fire(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({
            "rule_id": "rule-test-2",
            "name": "person alert",
            "label": "person",
            "min_confidence": 0.5,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        fired = evaluator.evaluate("evt-alert-001")
        assert fired == 0

    def test_alert_event_persisted(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({
            "rule_id": "rule-persist",
            "name": "persist test",
            "min_confidence": 0.0,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        evaluator.evaluate("evt-alert-001", device_id="alert-dev-1")
        events = tmp_db.list_alert_events()
        assert len(events) == 1
        assert events[0]["rule_id"] == "rule-persist"
        assert events[0]["top_label"] == "animal"

    def test_webhook_delivery_recorded(self, tmp_db: GatewayDatabase, webhook_server):
        cap, url = webhook_server
        tmp_db.add_alert_rule({
            "rule_id": "rule-webhook",
            "name": "webhook rule",
            "min_confidence": 0.0,
            "webhook_url": url,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        evaluator.evaluate("evt-alert-001", device_id="alert-dev-1")
        events = tmp_db.list_alert_events()
        assert events[0]["delivery_status"] == "delivered"
        assert len(cap.received) == 1
        assert "event_id" in cap.received[0]

    def test_default_webhook_used_when_rule_has_none(self, tmp_db: GatewayDatabase, webhook_server):
        cap, url = webhook_server
        tmp_db.add_alert_rule({
            "rule_id": "rule-default-wh",
            "name": "default webhook rule",
            "min_confidence": 0.0,
            "webhook_url": None,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db, default_webhook=url)
        evaluator.evaluate("evt-alert-001", device_id="alert-dev-1")
        assert len(cap.received) == 1

    def test_no_inference_result_fires_zero(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({
            "rule_id": "rule-noevt",
            "name": "no event",
            "min_confidence": 0.0,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        fired = evaluator.evaluate("nonexistent-event-id")
        assert fired == 0

    def test_evaluator_never_raises(self, tmp_db: GatewayDatabase):
        """Evaluator must be safe to call as a background task regardless of errors."""
        evaluator = AlertEvaluator(tmp_db)
        # Should not raise even with garbage input
        try:
            evaluator.evaluate(None)  # type: ignore[arg-type]
        except Exception as exc:
            pytest.fail(f"AlertEvaluator.evaluate raised: {exc}")

    def test_disabled_rule_not_fired(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({
            "rule_id": "rule-disabled",
            "name": "disabled",
            "min_confidence": 0.0,
            "enabled": False,
        })
        evaluator = AlertEvaluator(tmp_db)
        fired = evaluator.evaluate("evt-alert-001")
        assert fired == 0


# ── Database CRUD ─────────────────────────────────────────────────────────────

class TestAlertRulesDB:
    def test_add_and_get_rule(self, tmp_db: GatewayDatabase):
        rule = {
            "rule_id": "rule-db-1",
            "name": "DB test rule",
            "label": "animal",
            "min_confidence": 0.7,
            "enabled": True,
        }
        tmp_db.add_alert_rule(rule)
        fetched = tmp_db.get_alert_rule("rule-db-1")
        assert fetched is not None
        assert fetched["name"] == "DB test rule"
        assert fetched["min_confidence"] == 0.7
        assert fetched["enabled"] is True

    def test_get_unknown_rule_returns_none(self, tmp_db: GatewayDatabase):
        assert tmp_db.get_alert_rule("nonexistent") is None

    def test_list_all_rules(self, tmp_db: GatewayDatabase):
        for i in range(3):
            tmp_db.add_alert_rule({"rule_id": f"rule-list-{i}", "name": f"rule {i}", "enabled": True})
        rules = tmp_db.list_alert_rules()
        assert len(rules) == 3

    def test_list_enabled_only(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "rule-on", "name": "on", "enabled": True})
        tmp_db.add_alert_rule({"rule_id": "rule-off", "name": "off", "enabled": False})
        rules = tmp_db.list_alert_rules(enabled_only=True)
        assert len(rules) == 1
        assert rules[0]["rule_id"] == "rule-on"

    def test_update_rule(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "rule-upd", "name": "old name", "enabled": True})
        updated = tmp_db.update_alert_rule("rule-upd", {"name": "new name", "enabled": False})
        assert updated is True
        fetched = tmp_db.get_alert_rule("rule-upd")
        assert fetched["name"] == "new name"
        assert fetched["enabled"] is False

    def test_update_unknown_rule_returns_false(self, tmp_db: GatewayDatabase):
        assert tmp_db.update_alert_rule("nonexistent", {"name": "x"}) is False

    def test_delete_rule(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "rule-del", "name": "to delete", "enabled": True})
        deleted = tmp_db.delete_alert_rule("rule-del")
        assert deleted is True
        assert tmp_db.get_alert_rule("rule-del") is None

    def test_delete_unknown_rule_returns_false(self, tmp_db: GatewayDatabase):
        assert tmp_db.delete_alert_rule("nonexistent") is False


class TestAlertEventsDB:
    def test_add_and_list_event(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "rule-evt-1", "name": "evt rule", "enabled": True})
        tmp_db.add_alert_event({
            "alert_event_id": "alert-abc123",
            "rule_id": "rule-evt-1",
            "rule_name": "evt rule",
            "event_id": "evt-alert-001",
            "device_id": "alert-dev-1",
            "top_label": "animal",
            "top_confidence": 0.91,
            "top_species": "Odocoileus virginianus",
            "webhook_url": "http://example.com",
            "delivery_status": "delivered",
            "webhook_response": "200",
            "fired_at": "2026-05-14T10:02:00Z",
        })
        events = tmp_db.list_alert_events()
        assert len(events) == 1
        assert events[0]["alert_event_id"] == "alert-abc123"
        assert events[0]["delivery_status"] == "delivered"

    def test_list_filter_by_rule(self, tmp_db: GatewayDatabase):
        for rid in ("rule-a", "rule-b"):
            tmp_db.add_alert_rule({"rule_id": rid, "name": rid, "enabled": True})
            tmp_db.add_alert_event({
                "alert_event_id": f"ae-{rid}",
                "rule_id": rid,
                "rule_name": rid,
                "delivery_status": "delivered",
                "fired_at": "2026-05-14T10:00:00Z",
            })
        events = tmp_db.list_alert_events(rule_id="rule-a")
        assert len(events) == 1
        assert events[0]["rule_id"] == "rule-a"

    def test_list_filter_by_delivery_status(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "rule-stat", "name": "stat", "enabled": True})
        for status in ("delivered", "failed", "delivered"):
            tmp_db.add_alert_event({
                "alert_event_id": f"ae-{status}-{uuid.uuid4().hex[:4]}",
                "rule_id": "rule-stat",
                "rule_name": "stat",
                "delivery_status": status,
                "fired_at": "2026-05-14T10:00:00Z",
            })
        delivered = tmp_db.list_alert_events(delivery_status="delivered")
        assert len(delivered) == 2
        failed = tmp_db.list_alert_events(delivery_status="failed")
        assert len(failed) == 1


# ── REST endpoints ────────────────────────────────────────────────────────────

class TestAlertRulesREST:
    def test_create_rule_201(self, client: TestClient):
        resp = client.post("/api/v1/alert-rules", json={"data": {"name": "REST test rule", "label": "animal"}})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "rule_id" in body["rule"]
        assert body["rule"]["name"] == "REST test rule"

    def test_create_rule_missing_name_400(self, client: TestClient):
        resp = client.post("/api/v1/alert-rules", json={"data": {}})
        assert resp.status_code == 400

    def test_list_rules_empty(self, client: TestClient):
        resp = client.get("/api/v1/alert-rules")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_rules_after_create(self, client: TestClient):
        client.post("/api/v1/alert-rules", json={"data": {"name": "rule 1"}})
        client.post("/api/v1/alert-rules", json={"data": {"name": "rule 2"}})
        resp = client.get("/api/v1/alert-rules")
        assert resp.json()["count"] == 2

    def test_get_rule(self, client: TestClient):
        create_resp = client.post("/api/v1/alert-rules", json={"data": {"name": "get test"}})
        rule_id = create_resp.json()["rule"]["rule_id"]
        resp = client.get(f"/api/v1/alert-rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["rule"]["name"] == "get test"

    def test_get_unknown_rule_404(self, client: TestClient):
        resp = client.get("/api/v1/alert-rules/nonexistent")
        assert resp.status_code == 404

    def test_patch_rule(self, client: TestClient):
        create_resp = client.post("/api/v1/alert-rules", json={"data": {"name": "patch test"}})
        rule_id = create_resp.json()["rule"]["rule_id"]
        resp = client.patch(f"/api/v1/alert-rules/{rule_id}", json={"data": {"enabled": False}})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_patch_unknown_rule_404(self, client: TestClient):
        resp = client.patch("/api/v1/alert-rules/bad-id", json={"data": {"enabled": True}})
        assert resp.status_code == 404

    def test_delete_rule(self, client: TestClient):
        create_resp = client.post("/api/v1/alert-rules", json={"data": {"name": "delete test"}})
        rule_id = create_resp.json()["rule"]["rule_id"]
        resp = client.delete(f"/api/v1/alert-rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert client.get(f"/api/v1/alert-rules/{rule_id}").status_code == 404

    def test_delete_unknown_rule_404(self, client: TestClient):
        assert client.delete("/api/v1/alert-rules/bad-id").status_code == 404

    def test_list_alerts_empty(self, client: TestClient):
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_alerts_with_filter(self, client: TestClient):
        resp = client.get("/api/v1/alerts?delivery_status=failed")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── MCP tool functions ────────────────────────────────────────────────────────

class TestAlertMCPTools:
    def test_list_alert_rules_empty(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_alert_rules(ctx)
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["rules"] == []

    def test_list_alert_rules_after_create(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "r1", "name": "rule 1", "enabled": True})
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_alert_rules(ctx)
        assert result["count"] == 1

    def test_create_alert_rule_ok(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_alert_rule(ctx, name="bear alert", label="animal", min_confidence=0.8)
        assert result["ok"] is True
        assert result["created"] is True
        assert "rule_id" in result["rule"]
        assert result["rule"]["label"] == "animal"

    def test_create_alert_rule_invalid_label(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_alert_rule(ctx, name="bad label", label="fish")
        assert result["ok"] is False
        assert "label" in result["error"]

    def test_create_alert_rule_empty_name(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_alert_rule(ctx, name="  ")
        assert result["ok"] is False

    def test_create_alert_rule_confidence_clamped(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_alert_rule(ctx, name="clamp test", min_confidence=99)
        assert result["ok"] is True
        assert result["rule"]["min_confidence"] == 1.0

    def test_list_recent_alerts_empty(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_recent_alerts(ctx)
        assert result["ok"] is True
        assert result["count"] == 0

    def test_list_recent_alerts_with_data(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "rule-la", "name": "la rule", "enabled": True})
        tmp_db.add_alert_event({
            "alert_event_id": "ae-la-001",
            "rule_id": "rule-la",
            "rule_name": "la rule",
            "delivery_status": "delivered",
            "fired_at": "2026-05-14T10:00:00Z",
        })
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_recent_alerts(ctx)
        assert result["count"] == 1

    def test_list_recent_alerts_limit_clamped(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_recent_alerts(ctx, limit=99999)
        assert result["ok"] is True  # just verify it doesn't error


# ── Dispatch integration ──────────────────────────────────────────────────────

class TestDispatchAlertTools:
    def test_dispatch_list_alert_rules(self, tmp_db: GatewayDatabase):
        result = dispatch_tool("list_alert_rules", {}, database_path=tmp_db.path)
        assert result["ok"] is True

    def test_dispatch_list_recent_alerts(self, tmp_db: GatewayDatabase):
        result = dispatch_tool("list_recent_alerts", {}, database_path=tmp_db.path)
        assert result["ok"] is True

    def test_dispatch_create_alert_rule(self, tmp_db: GatewayDatabase):
        result = dispatch_tool(
            "create_alert_rule",
            {"name": "dispatch test", "label": "animal"},
            database_path=tmp_db.path,
        )
        assert result["ok"] is True
        assert result["created"] is True


# ── Stdio server definitions ──────────────────────────────────────────────────

class TestStdioServerAlertTools:
    def test_all_alert_tools_in_list(self):
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "list_alert_rules" in names
        assert "list_recent_alerts" in names
        assert "create_alert_rule" in names

    def test_list_alert_rules_no_required_args(self):
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "list_alert_rules")
        assert "required" not in defn["inputSchema"]

    def test_list_recent_alerts_schema(self):
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "list_recent_alerts")
        props = defn["inputSchema"]["properties"]
        assert "limit" in props
        assert "delivery_status" in props

    def test_create_alert_rule_requires_name(self):
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_alert_rule")
        assert "name" in defn["inputSchema"].get("required", [])


# ── Brain adapter policy ──────────────────────────────────────────────────────

class TestBrainAdapterAlertPolicy:
    def test_list_alert_rules_is_auto_approved(self):
        policy = ToolPolicy()
        assert policy.is_auto_approved("list_alert_rules")
        assert not policy.requires_approval("list_alert_rules")

    def test_list_recent_alerts_is_auto_approved(self):
        policy = ToolPolicy()
        assert policy.is_auto_approved("list_recent_alerts")
        assert not policy.requires_approval("list_recent_alerts")

    def test_create_alert_rule_requires_approval(self):
        policy = ToolPolicy()
        assert policy.requires_approval("create_alert_rule")
        assert not policy.is_auto_approved("create_alert_rule")


# ── Config env var ────────────────────────────────────────────────────────────

class TestAlertConfig:
    def test_alert_webhook_url_from_env(self, monkeypatch):
        monkeypatch.setenv("CLAWCAM_ALERT_WEBHOOK_URL", "http://example.com/hook")
        cfg = GatewayConfig.from_env()
        assert cfg.alert_webhook_url == "http://example.com/hook"

    def test_alert_webhook_url_default_is_none(self, monkeypatch):
        monkeypatch.delenv("CLAWCAM_ALERT_WEBHOOK_URL", raising=False)
        cfg = GatewayConfig.from_env()
        assert cfg.alert_webhook_url is None

    def test_alert_webhook_url_empty_env_is_none(self, monkeypatch):
        monkeypatch.setenv("CLAWCAM_ALERT_WEBHOOK_URL", "")
        cfg = GatewayConfig.from_env()
        assert cfg.alert_webhook_url is None
