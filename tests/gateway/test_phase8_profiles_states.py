"""Phase 8 tests: device profiles + runtime state machine.

Coverage
--------
- Profile catalog: every PROFILES entry has a ProfileDefaults row;
  is_valid_profile is honest; security profiles get higher priority weight
- State vocabulary: STATES enum, is_valid_state, DEFAULT_STATE
- DB: profile + state columns; set/get profile + state; state transitions
  audit log; deployment-level state; filter by target_kind / target_id
- AlertRule state gating: required_state matches / blocks / state-agnostic;
  to_dict/from_dict round-trip preserves required_state
- AlertEvaluator: device state used to gate rules; falls back to deployment
  state when device state unset; missing device → state-required rules
  don't fire (safe default)
- REST: list profiles, get profile, get/set device state, set deployment
  state, get state-transition history, invalid-state 400 / unknown-device 404
- MCP tools: list_profiles, get_device_state, list_state_transitions
  (auto-approved); set_device_state, set_deployment_state (approval-gated)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
_BRAIN_DIR = _REPO / "brain" / "oh-ben-claw-adapter"
for _p in (_GW, _BRAIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient

from clawcam_gateway.alerts.evaluator import AlertEvaluator
from clawcam_gateway.alerts.rules import AlertRule
from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.mcp_server.stdio_server import TOOL_DEFINITIONS
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.profiles import (
    DEFAULT_PROFILE,
    DEFAULT_STATE,
    PROFILES,
    STATES,
    STATE_ARMED,
    STATE_AWAY,
    STATE_DISARMED,
    STATE_FEEDING,
    STATE_NORMAL,
    PROFILE_BIRD_FEEDER,
    PROFILE_HOME_SECURITY_INDOOR,
    PROFILE_HOME_SECURITY_OUTDOOR,
    PROFILE_WILDLIFE,
    get_profile_defaults,
    is_valid_profile,
    is_valid_state,
)
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    get_device_state as tool_get_device_state,
    list_profiles as tool_list_profiles,
    list_state_transitions as tool_list_transitions,
    set_deployment_state as tool_set_deployment_state,
    set_device_state as tool_set_device_state,
)
from clawcam_adapter import ToolPolicy  # type: ignore[import]


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _seed_device(db: GatewayDatabase, device_id: str = "node-p8") -> None:
    db.upsert_device({
        "device_id": device_id,
        "device_type": "node",
        "name": "Phase 8 Node",
        "status": "active",
        "created_at": "2026-05-15T00:00:00Z",
        "last_seen_at": "2026-05-15T00:00:00Z",
    })


@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "test.db")
    _seed_device(db)
    return db


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, GatewayDatabase]:
    cfg = GatewayConfig(
        database_path=tmp_path / "test.db",
        media_dir=tmp_path / "media",
        auth_enabled=False,
    )
    app = create_app(config=cfg)
    db = GatewayDatabase(cfg.database_path)
    _seed_device(db)
    return TestClient(app), db


# ── Profile catalog ──────────────────────────────────────────────────────────

class TestProfileCatalog:
    def test_every_profile_has_defaults(self):
        for p in PROFILES:
            defaults = get_profile_defaults(p)
            assert defaults.profile == p
            assert defaults.description
            assert isinstance(defaults.default_detectors, tuple)
            assert len(defaults.default_detectors) >= 1

    def test_is_valid_profile(self):
        assert is_valid_profile(PROFILE_WILDLIFE)
        assert is_valid_profile(PROFILE_BIRD_FEEDER)
        assert not is_valid_profile("not_a_real_profile")
        assert not is_valid_profile(None)

    def test_default_profile_is_general(self):
        assert DEFAULT_PROFILE == "general"

    def test_security_profiles_have_higher_priority(self):
        wild = get_profile_defaults(PROFILE_WILDLIFE)
        outdoor = get_profile_defaults(PROFILE_HOME_SECURITY_OUTDOOR)
        indoor = get_profile_defaults(PROFILE_HOME_SECURITY_INDOOR)
        assert outdoor.alert_priority_weight > wild.alert_priority_weight
        assert indoor.alert_priority_weight >= outdoor.alert_priority_weight

    def test_unknown_profile_returns_default(self):
        defaults = get_profile_defaults("not_real")
        assert defaults.profile == DEFAULT_PROFILE

    def test_bird_feeder_has_audio_enabled(self):
        assert get_profile_defaults(PROFILE_BIRD_FEEDER).audio_enabled

    def test_security_profiles_continuous(self):
        assert get_profile_defaults(PROFILE_HOME_SECURITY_OUTDOOR).capture_continuous
        assert get_profile_defaults(PROFILE_HOME_SECURITY_INDOOR).capture_continuous

    def test_wildlife_is_not_continuous(self):
        assert not get_profile_defaults(PROFILE_WILDLIFE).capture_continuous

    def test_profile_dict_round_trip(self):
        d = get_profile_defaults(PROFILE_BIRD_FEEDER).to_dict()
        assert d["profile"] == PROFILE_BIRD_FEEDER
        assert "default_detectors" in d
        assert d["audio_enabled"] is True


# ── State vocabulary ─────────────────────────────────────────────────────────

class TestStateVocabulary:
    def test_default_state_is_normal(self):
        assert DEFAULT_STATE == "normal"

    def test_all_named_states_valid(self):
        for s in (STATE_NORMAL, STATE_ARMED, STATE_DISARMED, STATE_AWAY,
                  STATE_FEEDING):
            assert is_valid_state(s)

    def test_unknown_state_rejected(self):
        assert not is_valid_state("haunted")
        assert not is_valid_state(None)
        assert not is_valid_state("")

    def test_state_enum_completeness(self):
        # If a new state is added the suite below should be extended.
        assert len(STATES) == 7


# ── Database ─────────────────────────────────────────────────────────────────

class TestProfileStateDB:
    def test_new_device_defaults_to_general_normal(self, tmp_db: GatewayDatabase):
        row = tmp_db.get_device_profile_state("node-p8")
        assert row is not None
        assert row["profile"] == DEFAULT_PROFILE
        assert row["state"] == DEFAULT_STATE
        assert row["deployment_id"] == "default"

    def test_set_device_profile(self, tmp_db: GatewayDatabase):
        assert tmp_db.set_device_profile("node-p8", PROFILE_HOME_SECURITY_OUTDOOR)
        row = tmp_db.get_device_profile_state("node-p8")
        assert row["profile"] == PROFILE_HOME_SECURITY_OUTDOOR

    def test_set_device_state_records_transition(self, tmp_db: GatewayDatabase):
        ok, prev = tmp_db.set_device_state(
            "node-p8", STATE_ARMED, transitioned_by="test", reason="unit test")
        assert ok
        assert prev == STATE_NORMAL
        assert tmp_db.get_device_profile_state("node-p8")["state"] == STATE_ARMED
        history = tmp_db.list_state_transitions(target_kind="device", target_id="node-p8")
        assert len(history) == 1
        assert history[0]["from_state"] == STATE_NORMAL
        assert history[0]["to_state"] == STATE_ARMED
        assert history[0]["reason"] == "unit test"

    def test_set_state_unknown_device(self, tmp_db: GatewayDatabase):
        ok, prev = tmp_db.set_device_state("does-not-exist", STATE_ARMED)
        assert not ok
        assert prev is None

    def test_multiple_transitions_recorded(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_state("node-p8", STATE_ARMED)
        tmp_db.set_device_state("node-p8", STATE_AWAY)
        tmp_db.set_device_state("node-p8", STATE_DISARMED)
        history = tmp_db.list_state_transitions(target_kind="device", target_id="node-p8")
        assert len(history) == 3
        # Newest first
        assert history[0]["to_state"] == STATE_DISARMED
        assert history[1]["to_state"] == STATE_AWAY
        assert history[2]["to_state"] == STATE_ARMED

    def test_deployment_state_set_and_get(self, tmp_db: GatewayDatabase):
        assert tmp_db.get_deployment_state("default") == STATE_NORMAL
        ok, prev = tmp_db.set_deployment_state(
            "default", STATE_AWAY, reason="going on vacation")
        assert ok
        assert prev == STATE_NORMAL
        assert tmp_db.get_deployment_state("default") == STATE_AWAY

    def test_deployment_state_unknown_deployment(self, tmp_db: GatewayDatabase):
        ok, _ = tmp_db.set_deployment_state("nonexistent", STATE_AWAY)
        assert not ok

    def test_state_transitions_filter(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_state("node-p8", STATE_ARMED)
        tmp_db.set_deployment_state("default", STATE_AWAY)
        device_only = tmp_db.list_state_transitions(target_kind="device")
        deployment_only = tmp_db.list_state_transitions(target_kind="deployment")
        assert all(t["target_kind"] == "device" for t in device_only)
        assert all(t["target_kind"] == "deployment" for t in deployment_only)


# ── AlertRule state gating ───────────────────────────────────────────────────

class TestAlertRuleStateGate:
    @staticmethod
    def _result(**kw):
        d = {
            "top_label": "person",
            "top_confidence": 0.9,
            "top_species": None,
        }
        d.update(kw)
        return d

    def test_no_required_state_always_fires(self):
        rule = AlertRule(rule_id="r1", name="r", required_state=None,
                         min_confidence=0.0)
        assert rule.matches(self._result())
        assert rule.matches(self._result(), current_state=STATE_ARMED)
        assert rule.matches(self._result(), current_state=STATE_DISARMED)

    def test_required_state_match_fires(self):
        rule = AlertRule(rule_id="r2", name="r", required_state=STATE_ARMED,
                         min_confidence=0.0)
        assert rule.matches(self._result(), current_state=STATE_ARMED)

    def test_required_state_mismatch_blocks(self):
        rule = AlertRule(rule_id="r3", name="r", required_state=STATE_ARMED,
                         min_confidence=0.0)
        assert not rule.matches(self._result(), current_state=STATE_DISARMED)

    def test_required_state_unknown_state_blocks(self):
        """If we have no idea what state the device is in, fail safe."""
        rule = AlertRule(rule_id="r4", name="r", required_state=STATE_ARMED,
                         min_confidence=0.0)
        assert not rule.matches(self._result(), current_state=None)

    def test_to_dict_round_trip_preserves_required_state(self):
        rule = AlertRule(rule_id="r5", name="r", required_state=STATE_AWAY)
        round_tripped = AlertRule.from_dict(rule.to_dict())
        assert round_tripped.required_state == STATE_AWAY


# ── AlertEvaluator uses state ────────────────────────────────────────────────

class TestEvaluatorStateAware:
    def test_armed_rule_fires_when_armed(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_state("node-p8", STATE_ARMED)
        tmp_db.add_event({
            "event_id": "evt-state-1",
            "event_type": "motion_detected",
            "device_id": "node-p8",
            "timestamp": "2026-05-15T10:00:00Z",
            "time_source": "rtc",
            "source": "node",
            "media": [],
            "metadata": {},
        })
        tmp_db.save_inference_result(
            "evt-state-1", "/m/x.jpg",
            InferenceResult(
                model_name="mock", model_version="1",
                detections=[Detection("person", 0.95, [0, 0, 1, 1], None)],
            ),
        )
        tmp_db.add_alert_rule({
            "rule_id": "armed-rule",
            "name": "armed only",
            "label": "person",
            "min_confidence": 0.5,
            "required_state": STATE_ARMED,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        fired = evaluator.evaluate("evt-state-1", device_id="node-p8")
        assert fired == 1

    def test_armed_rule_blocked_when_disarmed(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_state("node-p8", STATE_DISARMED)
        tmp_db.add_event({
            "event_id": "evt-state-2",
            "event_type": "motion_detected",
            "device_id": "node-p8",
            "timestamp": "2026-05-15T10:00:00Z",
            "time_source": "rtc",
            "source": "node",
            "media": [],
            "metadata": {},
        })
        tmp_db.save_inference_result(
            "evt-state-2", "/m/x.jpg",
            InferenceResult(
                model_name="mock", model_version="1",
                detections=[Detection("person", 0.95, [0, 0, 1, 1], None)],
            ),
        )
        tmp_db.add_alert_rule({
            "rule_id": "armed-rule",
            "name": "armed only",
            "label": "person",
            "required_state": STATE_ARMED,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        fired = evaluator.evaluate("evt-state-2", device_id="node-p8")
        assert fired == 0


# ── REST endpoints ───────────────────────────────────────────────────────────

class TestProfileStateREST:
    def test_list_profiles(self, client):
        c, _ = client
        body = c.get("/api/v1/profiles").json()
        assert body["ok"]
        names = {p["profile"] for p in body["profiles"]}
        assert PROFILE_BIRD_FEEDER in names
        assert PROFILE_HOME_SECURITY_INDOOR in names
        assert PROFILE_WILDLIFE in names

    def test_get_profile(self, client):
        c, _ = client
        resp = c.get(f"/api/v1/profiles/{PROFILE_BIRD_FEEDER}")
        assert resp.status_code == 200
        assert resp.json()["profile"]["audio_enabled"] is True

    def test_get_unknown_profile_404(self, client):
        c, _ = client
        assert c.get("/api/v1/profiles/zzz").status_code == 404

    def test_get_device_state(self, client):
        c, _ = client
        body = c.get("/api/v1/devices/node-p8/state").json()
        assert body["device_id"] == "node-p8"
        assert body["state"] == STATE_NORMAL
        assert body["effective_state"] == STATE_NORMAL

    def test_get_unknown_device_state_404(self, client):
        c, _ = client
        assert c.get("/api/v1/devices/missing/state").status_code == 404

    def test_set_device_state(self, client):
        c, db = client
        resp = c.patch("/api/v1/devices/node-p8/state",
                       json={"data": {"state": STATE_ARMED, "reason": "test"}})
        assert resp.status_code == 200
        assert resp.json()["state"] == STATE_ARMED
        assert db.get_device_profile_state("node-p8")["state"] == STATE_ARMED

    def test_set_invalid_state_400(self, client):
        c, _ = client
        assert c.patch("/api/v1/devices/node-p8/state",
                       json={"data": {"state": "haunted"}}).status_code == 400

    def test_set_profile(self, client):
        c, db = client
        resp = c.patch("/api/v1/devices/node-p8/profile",
                       json={"data": {"profile": PROFILE_HOME_SECURITY_OUTDOOR}})
        assert resp.status_code == 200
        assert db.get_device_profile_state("node-p8")["profile"] == PROFILE_HOME_SECURITY_OUTDOOR

    def test_set_invalid_profile_400(self, client):
        c, _ = client
        assert c.patch("/api/v1/devices/node-p8/profile",
                       json={"data": {"profile": "fake"}}).status_code == 400

    def test_set_deployment_state(self, client):
        c, _ = client
        resp = c.patch("/api/v1/deployments/default/state",
                       json={"data": {"state": STATE_AWAY}})
        assert resp.status_code == 200
        assert resp.json()["state"] == STATE_AWAY

    def test_state_transitions_history(self, client):
        c, _ = client
        c.patch("/api/v1/devices/node-p8/state", json={"data": {"state": STATE_ARMED}})
        c.patch("/api/v1/devices/node-p8/state", json={"data": {"state": STATE_AWAY}})
        body = c.get("/api/v1/state-transitions?target_kind=device&target_id=node-p8").json()
        assert body["count"] == 2


# ── MCP tools ────────────────────────────────────────────────────────────────

class TestProfileStateTools:
    def test_list_profiles_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_profiles(ctx)
        assert result["ok"]
        assert result["count"] == len(PROFILES)

    def test_get_device_state_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_get_device_state(ctx, device_id="node-p8")
        assert result["ok"]
        assert result["state"] == STATE_NORMAL

    def test_get_unknown_device_state_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_get_device_state(ctx, device_id="not_there")
        assert not result["ok"]

    def test_set_device_state_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_set_device_state(ctx, device_id="node-p8", state=STATE_ARMED,
                                       reason="phase 8 test")
        assert result["ok"]
        assert result["state"] == STATE_ARMED

    def test_set_invalid_state_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_set_device_state(ctx, device_id="node-p8", state="bogus")
        assert not result["ok"]

    def test_set_deployment_state_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_set_deployment_state(ctx, deployment_id="default", state=STATE_FEEDING)
        assert result["ok"]
        assert result["state"] == STATE_FEEDING

    def test_list_state_transitions_tool(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_state("node-p8", STATE_ARMED)
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_transitions(ctx)
        assert result["ok"]
        assert result["count"] >= 1


# ── Dispatch + stdio + policy ────────────────────────────────────────────────

class TestPhase8Dispatch:
    def test_dispatch_list_profiles(self, tmp_db: GatewayDatabase):
        assert dispatch_tool("list_profiles", {}, database_path=tmp_db.path)["ok"]

    def test_dispatch_set_device_state(self, tmp_db: GatewayDatabase):
        result = dispatch_tool(
            "set_device_state",
            {"device_id": "node-p8", "state": STATE_ARMED},
            database_path=tmp_db.path,
        )
        assert result["ok"]

    def test_stdio_lists_all_new_tools(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        for required in ("list_profiles", "get_device_state",
                          "list_state_transitions",
                          "set_device_state", "set_deployment_state"):
            assert required in names

    def test_brain_adapter_policy(self):
        policy = ToolPolicy()
        for read_tool in ("list_profiles", "get_device_state",
                          "list_state_transitions"):
            assert policy.is_auto_approved(read_tool)
        for write_tool in ("set_device_state", "set_deployment_state"):
            assert policy.requires_approval(write_tool)
