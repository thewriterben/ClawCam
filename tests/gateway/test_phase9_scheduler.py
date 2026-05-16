"""Phase 9 tests: schedule engine + cron-driven action dispatch.

Coverage
--------
- action vocabulary + validator
- DB CRUD: schedules + schedule_runs; round-trip of action_payload JSON
- ``ScheduleEngine.tick``: first-sight computes next_run_at without firing;
  fires when next_run_at <= now; reschedules from cron; one-shot disables
  itself; ``starts_at`` / ``ends_at`` gating
- action handlers: set_state, set_deployment_state, enable_rule,
  disable_rule, webhook (success + failure)
- ``run_now``: manual trigger fires regardless of next_run_at
- REST: full CRUD; cron-expression validation rejects bad strings;
  ``run`` endpoint; ``schedule-runs`` history
- MCP tools: list_schedules, list_schedule_runs (auto-approved);
  create_schedule (approval-gated)
- Brain adapter policy classification
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
_BRAIN_DIR = _REPO / "brain" / "oh-ben-claw-adapter"
for _p in (_GW, _BRAIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.mcp_server.stdio_server import TOOL_DEFINITIONS
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.profiles import STATE_ARMED, STATE_AWAY, STATE_NORMAL
from clawcam_gateway.scheduler import (
    ACTION_DISABLE_RULE,
    ACTION_ENABLE_RULE,
    ACTION_SET_DEPLOYMENT_STATE,
    ACTION_SET_STATE,
    ACTION_TYPES,
    ACTION_WEBHOOK,
    ScheduleEngine,
    is_valid_action,
)
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    create_schedule as tool_create_schedule,
    list_schedule_runs as tool_list_runs,
    list_schedules as tool_list_schedules,
)
from clawcam_adapter import ToolPolicy  # type: ignore[import]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "test.db")
    db.upsert_device({
        "device_id": "node-sched",
        "device_type": "node",
        "name": "Scheduler Test Node",
        "status": "active",
        "created_at": "2026-05-15T00:00:00Z",
        "last_seen_at": "2026-05-15T00:00:00Z",
    })
    return db


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, GatewayDatabase]:
    cfg = GatewayConfig(
        database_path=tmp_path / "test.db",
        media_dir=tmp_path / "media",
        scheduler_enabled=False,  # tests drive tick() directly
    )
    app = create_app(config=cfg)
    db = GatewayDatabase(cfg.database_path)
    db.upsert_device({
        "device_id": "node-sched",
        "device_type": "node",
        "name": "Scheduler Test Node",
        "status": "active",
        "created_at": "2026-05-15T00:00:00Z",
        "last_seen_at": "2026-05-15T00:00:00Z",
    })
    return TestClient(app), db


def _make_engine(db: GatewayDatabase, webhook_results: list | None = None) -> ScheduleEngine:
    """Build an engine wired with a recording webhook deliverer."""

    def fake_webhook(url: str, body: dict, timeout: int = 5):
        if webhook_results is not None:
            webhook_results.append({"url": url, "body": body})
        if url.startswith("http://fail"):
            return (False, None, "unreachable")
        return (True, 200, None)

    return ScheduleEngine(db=db, webhook_deliverer=fake_webhook)


# ── Action vocabulary ────────────────────────────────────────────────────────

class TestActionVocabulary:
    def test_action_types_set(self):
        assert set(ACTION_TYPES) == {
            ACTION_SET_STATE,
            ACTION_SET_DEPLOYMENT_STATE,
            ACTION_ENABLE_RULE,
            ACTION_DISABLE_RULE,
            ACTION_WEBHOOK,
        }

    def test_is_valid_action(self):
        assert is_valid_action(ACTION_WEBHOOK)
        assert not is_valid_action("nope")
        assert not is_valid_action(None)


# ── DB CRUD ─────────────────────────────────────────────────────────────────

class TestScheduleDB:
    def test_add_and_get(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s1",
            "name": "evening arm",
            "action_type": ACTION_SET_DEPLOYMENT_STATE,
            "action_payload": {"deployment_id": "default", "state": STATE_ARMED},
            "cron_expr": "0 22 * * *",
        })
        d = tmp_db.get_schedule("s1")
        assert d is not None
        assert d["name"] == "evening arm"
        assert d["action_payload"]["state"] == STATE_ARMED

    def test_get_unknown_returns_none(self, tmp_db: GatewayDatabase):
        assert tmp_db.get_schedule("nope") is None

    def test_list_filter_enabled(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({"schedule_id": "s-on", "name": "on",
                              "action_type": ACTION_WEBHOOK, "enabled": True})
        tmp_db.add_schedule({"schedule_id": "s-off", "name": "off",
                              "action_type": ACTION_WEBHOOK, "enabled": False})
        all_ = tmp_db.list_schedules()
        enabled = tmp_db.list_schedules(enabled_only=True)
        assert len(all_) == 2
        assert len(enabled) == 1
        assert enabled[0]["schedule_id"] == "s-on"

    def test_update(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({"schedule_id": "s-upd", "name": "old",
                              "action_type": ACTION_WEBHOOK})
        assert tmp_db.update_schedule("s-upd", {"name": "new", "enabled": False,
                                                 "action_payload": {"url": "x"}})
        d = tmp_db.get_schedule("s-upd")
        assert d["name"] == "new"
        assert d["enabled"] is False
        assert d["action_payload"]["url"] == "x"

    def test_update_unknown_returns_false(self, tmp_db: GatewayDatabase):
        assert not tmp_db.update_schedule("missing", {"name": "x"})

    def test_delete(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({"schedule_id": "s-del", "name": "x",
                              "action_type": ACTION_WEBHOOK})
        assert tmp_db.delete_schedule("s-del")
        assert tmp_db.get_schedule("s-del") is None

    def test_record_run_dict_form(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({"schedule_id": "s-run", "name": "x",
                              "action_type": ACTION_WEBHOOK})
        tmp_db.record_schedule_run({
            "schedule_id": "s-run",
            "status": "success",
            "detail": {"url": "x"},
            "error": None,
        })
        runs = tmp_db.list_schedule_runs(schedule_id="s-run")
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["detail"]["url"] == "x"


# ── Engine tick semantics ────────────────────────────────────────────────────

class TestEngineTick:
    def test_first_sight_does_not_fire(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s-first",
            "name": "first sight",
            "action_type": ACTION_WEBHOOK,
            "action_payload": {"url": "http://example.test/"},
            "cron_expr": "0 12 * * *",  # noon
        })
        engine = _make_engine(tmp_db)
        # 11:00 — schedule has never run; engine should compute next_run_at
        # but NOT fire on this tick.
        results = engine.tick(datetime(2026, 5, 15, 11, 0, tzinfo=timezone.utc))
        assert results == []
        d = tmp_db.get_schedule("s-first")
        assert d["next_run_at"] is not None
        # 11:30 — still before noon, still no fire.
        results = engine.tick(datetime(2026, 5, 15, 11, 30, tzinfo=timezone.utc))
        assert results == []

    def test_fires_when_next_run_at_in_past(self, tmp_db: GatewayDatabase):
        webhook_log: list = []
        tmp_db.add_schedule({
            "schedule_id": "s-fire",
            "name": "noon webhook",
            "action_type": ACTION_WEBHOOK,
            "action_payload": {"url": "http://example.test/hit"},
            "cron_expr": "0 12 * * *",
            "next_run_at": "2026-05-15T12:00:00+00:00",
        })
        engine = _make_engine(tmp_db, webhook_log)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert len(results) == 1
        assert results[0].status == "success"
        assert webhook_log == [{"url": "http://example.test/hit", "body": {}}]
        # next_run_at should be advanced to tomorrow
        d = tmp_db.get_schedule("s-fire")
        assert d["next_run_at"] is not None
        assert d["next_run_at"] > "2026-05-15T12:00:00+00:00"

    def test_one_shot_disables_after_firing(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s-once",
            "name": "one shot",
            "action_type": ACTION_WEBHOOK,
            "action_payload": {"url": "http://example.test/"},
            "next_run_at": "2026-05-15T00:00:00+00:00",  # already due
        })
        engine = _make_engine(tmp_db)
        engine.tick(datetime(2026, 5, 15, 1, 0, tzinfo=timezone.utc))
        d = tmp_db.get_schedule("s-once")
        assert d["enabled"] is False

    def test_starts_at_gates_firing(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s-future",
            "name": "future",
            "action_type": ACTION_WEBHOOK,
            "action_payload": {"url": "http://example.test/"},
            "starts_at": "2027-01-01T00:00:00+00:00",
            "next_run_at": "2026-05-15T00:00:00+00:00",
        })
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results == []

    def test_ends_at_gates_firing(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s-expired",
            "name": "expired",
            "action_type": ACTION_WEBHOOK,
            "action_payload": {"url": "http://example.test/"},
            "ends_at": "2025-01-01T00:00:00+00:00",
            "next_run_at": "2026-05-15T00:00:00+00:00",
        })
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results == []

    def test_disabled_schedule_skipped(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s-disabled",
            "name": "disabled",
            "action_type": ACTION_WEBHOOK,
            "action_payload": {"url": "x"},
            "next_run_at": "2026-05-15T00:00:00+00:00",
            "enabled": False,
        })
        engine = _make_engine(tmp_db)
        assert engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)) == []


# ── Action handlers ─────────────────────────────────────────────────────────

class TestActionHandlers:
    def _push_due_schedule(self, db: GatewayDatabase, action_type: str,
                           payload: dict, schedule_id: str = "s") -> None:
        db.add_schedule({
            "schedule_id": schedule_id,
            "name": action_type,
            "action_type": action_type,
            "action_payload": payload,
            "next_run_at": "2026-05-15T00:00:00+00:00",
        })

    def test_set_state(self, tmp_db: GatewayDatabase):
        self._push_due_schedule(tmp_db, ACTION_SET_STATE,
                                {"device_id": "node-sched", "state": STATE_ARMED},
                                schedule_id="s-state")
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results[0].status == "success"
        assert tmp_db.get_device_profile_state("node-sched")["state"] == STATE_ARMED

    def test_set_state_unknown_device(self, tmp_db: GatewayDatabase):
        self._push_due_schedule(tmp_db, ACTION_SET_STATE,
                                {"device_id": "missing", "state": STATE_ARMED},
                                schedule_id="s-bad")
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results[0].status == "failed"
        assert "unknown device" in results[0].error

    def test_set_deployment_state(self, tmp_db: GatewayDatabase):
        self._push_due_schedule(tmp_db, ACTION_SET_DEPLOYMENT_STATE,
                                {"state": STATE_AWAY},
                                schedule_id="s-dep")
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results[0].status == "success"
        assert tmp_db.get_deployment_state("default") == STATE_AWAY

    def test_enable_rule(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "r-toggle", "name": "x", "enabled": False})
        self._push_due_schedule(tmp_db, ACTION_ENABLE_RULE,
                                {"rule_id": "r-toggle"}, schedule_id="s-en")
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results[0].status == "success"
        assert tmp_db.get_alert_rule("r-toggle")["enabled"] is True

    def test_disable_rule(self, tmp_db: GatewayDatabase):
        tmp_db.add_alert_rule({"rule_id": "r-off", "name": "x", "enabled": True})
        self._push_due_schedule(tmp_db, ACTION_DISABLE_RULE,
                                {"rule_id": "r-off"}, schedule_id="s-dis")
        engine = _make_engine(tmp_db)
        engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert tmp_db.get_alert_rule("r-off")["enabled"] is False

    def test_webhook_success(self, tmp_db: GatewayDatabase):
        log: list = []
        self._push_due_schedule(tmp_db, ACTION_WEBHOOK,
                                {"url": "http://example.test/x",
                                 "body": {"a": 1}},
                                schedule_id="s-wh")
        engine = _make_engine(tmp_db, log)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results[0].status == "success"
        assert log == [{"url": "http://example.test/x", "body": {"a": 1}}]

    def test_webhook_failure_recorded(self, tmp_db: GatewayDatabase):
        self._push_due_schedule(tmp_db, ACTION_WEBHOOK,
                                {"url": "http://fail.invalid/"},
                                schedule_id="s-fail")
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results[0].status == "failed"

    def test_unknown_action_type(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s-weird",
            "name": "weird",
            "action_type": "do_a_dance",
            "action_payload": {},
            "next_run_at": "2026-05-15T00:00:00+00:00",
        })
        engine = _make_engine(tmp_db)
        results = engine.tick(datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc))
        assert results[0].status == "failed"
        assert "unknown action_type" in results[0].error


# ── run_now manual trigger ──────────────────────────────────────────────────

class TestRunNow:
    def test_run_now_fires_unconditionally(self, tmp_db: GatewayDatabase):
        tmp_db.add_schedule({
            "schedule_id": "s-manual",
            "name": "manual",
            "action_type": ACTION_SET_DEPLOYMENT_STATE,
            "action_payload": {"state": STATE_AWAY},
            "next_run_at": "2099-01-01T00:00:00+00:00",  # far future
        })
        engine = _make_engine(tmp_db)
        result = engine.run_now("s-manual")
        assert result.status == "success"
        assert tmp_db.get_deployment_state("default") == STATE_AWAY

    def test_run_now_unknown_schedule(self, tmp_db: GatewayDatabase):
        engine = _make_engine(tmp_db)
        result = engine.run_now("missing")
        assert result.status == "failed"


# ── REST surface ────────────────────────────────────────────────────────────

class TestScheduleREST:
    def test_create_and_list(self, client):
        c, _ = client
        resp = c.post("/api/v1/schedules", json={"data": {
            "name": "arm at 10pm",
            "action_type": ACTION_SET_DEPLOYMENT_STATE,
            "action_payload": {"state": STATE_ARMED},
            "cron_expr": "0 22 * * *",
        }})
        assert resp.status_code == 200
        assert c.get("/api/v1/schedules").json()["count"] == 1

    def test_create_missing_name_400(self, client):
        c, _ = client
        assert c.post("/api/v1/schedules", json={"data": {
            "action_type": ACTION_WEBHOOK,
        }}).status_code == 400

    def test_create_invalid_action_400(self, client):
        c, _ = client
        assert c.post("/api/v1/schedules", json={"data": {
            "name": "x", "action_type": "dance",
        }}).status_code == 400

    def test_create_invalid_cron_400(self, client):
        c, _ = client
        assert c.post("/api/v1/schedules", json={"data": {
            "name": "x", "action_type": ACTION_WEBHOOK,
            "cron_expr": "this is not cron",
        }}).status_code == 400

    def test_get_unknown_404(self, client):
        c, _ = client
        assert c.get("/api/v1/schedules/nope").status_code == 404

    def test_patch_schedule(self, client):
        c, _ = client
        create = c.post("/api/v1/schedules", json={"data": {
            "name": "old", "action_type": ACTION_WEBHOOK,
        }}).json()
        sid = create["schedule"]["schedule_id"]
        resp = c.patch(f"/api/v1/schedules/{sid}",
                       json={"data": {"name": "renamed"}})
        assert resp.status_code == 200
        assert resp.json()["schedule"]["name"] == "renamed"

    def test_delete_schedule(self, client):
        c, _ = client
        create = c.post("/api/v1/schedules", json={"data": {
            "name": "die", "action_type": ACTION_WEBHOOK,
        }}).json()
        sid = create["schedule"]["schedule_id"]
        assert c.delete(f"/api/v1/schedules/{sid}").status_code == 200
        assert c.get(f"/api/v1/schedules/{sid}").status_code == 404

    def test_run_endpoint_fires(self, client):
        c, db = client
        create = c.post("/api/v1/schedules", json={"data": {
            "name": "manual run",
            "action_type": ACTION_SET_DEPLOYMENT_STATE,
            "action_payload": {"state": STATE_AWAY},
        }}).json()
        sid = create["schedule"]["schedule_id"]
        resp = c.post(f"/api/v1/schedules/{sid}/run")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        # And the run is in the audit log
        runs = c.get("/api/v1/schedule-runs").json()["runs"]
        assert any(r["schedule_id"] == sid for r in runs)


# ── MCP tools ───────────────────────────────────────────────────────────────

class TestScheduleTools:
    def test_list_schedules_empty(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        assert tool_list_schedules(ctx)["count"] == 0

    def test_create_schedule_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_schedule(
            ctx,
            name="test schedule",
            action_type=ACTION_WEBHOOK,
            action_payload={"url": "http://x"},
        )
        assert result["ok"]
        assert "schedule_id" in result["schedule"]

    def test_create_schedule_invalid_action(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_schedule(ctx, name="x", action_type="garbage")
        assert not result["ok"]

    def test_create_schedule_invalid_cron(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_schedule(
            ctx, name="x", action_type=ACTION_WEBHOOK,
            cron_expr="absolutely not a cron string",
        )
        assert not result["ok"]

    def test_create_schedule_empty_name(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        assert not tool_create_schedule(ctx, name=" ", action_type=ACTION_WEBHOOK)["ok"]

    def test_list_runs_empty(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        assert tool_list_runs(ctx)["count"] == 0


# ── Dispatch + stdio + adapter ──────────────────────────────────────────────

class TestPhase9Wiring:
    def test_dispatch_list_schedules(self, tmp_db: GatewayDatabase):
        assert dispatch_tool("list_schedules", {}, database_path=tmp_db.path)["ok"]

    def test_dispatch_create_schedule(self, tmp_db: GatewayDatabase):
        result = dispatch_tool(
            "create_schedule",
            {"name": "dispatch test",
             "action_type": ACTION_WEBHOOK,
             "action_payload": {"url": "http://x"}},
            database_path=tmp_db.path,
        )
        assert result["ok"]

    def test_stdio_has_schedule_tools(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        for n in ("list_schedules", "list_schedule_runs", "create_schedule"):
            assert n in names

    def test_brain_adapter_policy(self):
        policy = ToolPolicy()
        assert policy.is_auto_approved("list_schedules")
        assert policy.is_auto_approved("list_schedule_runs")
        assert policy.requires_approval("create_schedule")
