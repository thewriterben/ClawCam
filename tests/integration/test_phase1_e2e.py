"""End-to-end Phase 1 integration test.

Exercises the complete data flow:
  Simulator → gateway import → Python tools → MCP stdio bridge → brain adapter

Each test layer builds on the previous one so a failure pinpoints the broken
boundary. All tests use temporary directories and databases so they are
fully isolated and can run in parallel.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent
GATEWAY_DIR = REPO_ROOT / "gateway"
BRAIN_DIR = REPO_ROOT / "brain" / "oh-ben-claw-adapter"

# Add gateway to path so imports work without installation
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))
if str(BRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_DIR))

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    apply_config_patch,
    capture_now,
    generate_daily_summary,
    get_node_health,
    get_recent_detections,
    list_pending_commands,
)
from clawcam_adapter import ApprovalRequired, ClawCamAdapter, ToolPolicy


# ── Fixtures ───────────────────────────────────────────────────────────────

EVENT_DATE = datetime(2026, 5, 12, 8, 0, tzinfo=timezone.utc)


@pytest.fixture()
def sim_bundle(tmp_path):
    """A simulator bundle written to disk."""
    node = SimulatedNode(
        device_id="e2e-node-01",
        deployment_id="e2e-deploy",
        name="E2E Test Camera",
    )
    bundle_dir = tmp_path / "bundle"
    paths = node.write_bundle(bundle_dir, EVENT_DATE)
    return bundle_dir, paths


@pytest.fixture()
def populated_db(tmp_path, sim_bundle):
    """A gateway database populated from the simulator bundle."""
    bundle_dir, _ = sim_bundle
    db_path = tmp_path / "gateway.db"
    db = GatewayDatabase(db_path)
    import_directory(bundle_dir, db)
    return db, db_path


@pytest.fixture()
def tool_context(populated_db):
    _, db_path = populated_db
    return ToolContext(database_path=db_path)


# ── Layer 1: Simulator ─────────────────────────────────────────────────────

class TestSimulator:
    def test_bundle_files_written(self, sim_bundle):
        _, paths = sim_bundle
        assert paths["device"].exists()
        assert paths["event"].exists()
        assert paths["health"].exists()

    def test_device_payload_valid_json(self, sim_bundle):
        _, paths = sim_bundle
        data = json.loads(paths["device"].read_text())
        assert data["device_id"] == "e2e-node-01"
        assert data["deployment_id"] == "e2e-deploy"

    def test_event_payload_has_classifications(self, sim_bundle):
        _, paths = sim_bundle
        data = json.loads(paths["event"].read_text())
        assert data["event_type"] == "capture"
        assert len(data.get("classifications", [])) > 0

    def test_health_payload_has_battery(self, sim_bundle):
        _, paths = sim_bundle
        data = json.loads(paths["health"].read_text())
        assert "battery" in data
        assert data["battery"]["percentage"] > 0


# ── Layer 2: Gateway import + database ────────────────────────────────────

class TestGatewayImport:
    def test_import_records_device_event_health(self, tmp_path, sim_bundle):
        bundle_dir, _ = sim_bundle
        db = GatewayDatabase(tmp_path / "gw.db")
        imported = import_directory(bundle_dir, db)
        assert any(i.startswith("device:e2e-node-01") for i in imported)
        assert any(i.startswith("event:") for i in imported)
        assert any(i.startswith("health:e2e-node-01") for i in imported)

    def test_device_queryable(self, populated_db):
        db, _ = populated_db
        device = db.get_device("e2e-node-01")
        assert device is not None
        assert device["deployment_id"] == "e2e-deploy"

    def test_event_queryable(self, populated_db):
        db, _ = populated_db
        events = db.recent_events(limit=10)
        assert len(events) == 1
        assert events[0]["device_id"] == "e2e-node-01"

    def test_health_queryable(self, populated_db):
        db, _ = populated_db
        health = db.latest_health("e2e-node-01")
        assert health is not None
        assert health["battery"]["percentage"] == 72


# ── Layer 3: Python tool functions ────────────────────────────────────────

class TestPythonTools:
    def test_get_recent_detections(self, tool_context):
        result = get_recent_detections(tool_context, limit=10)
        assert result["ok"] is True
        assert len(result["detections"]) == 1

    def test_get_node_health_found(self, tool_context):
        result = get_node_health(tool_context, "e2e-node-01")
        assert result["ok"] is True
        assert result["health"]["battery"]["percentage"] == 72

    def test_get_node_health_missing(self, tool_context):
        result = get_node_health(tool_context, "does-not-exist")
        assert result["ok"] is False
        assert "no health record" in result["error"]

    def test_generate_daily_summary(self, tool_context):
        result = generate_daily_summary(tool_context, report_date="2026-05-12")
        assert result["ok"] is True
        assert result["event_count"] == 1
        assert result["label_counts"].get("animal", 0) == 1

    def test_capture_now_queues_command(self, tool_context):
        result = capture_now(tool_context, "e2e-node-01", reason="e2e test")
        assert result["ok"] is True
        assert result["queued"] is True
        assert result["command_id"].startswith("cmd-capture-")
        assert result["status"] == "queued"

    def test_capture_now_unknown_device(self, tool_context):
        result = capture_now(tool_context, "ghost-node")
        assert result["ok"] is False
        assert "unknown device" in result["error"]

    def test_apply_config_patch_queues_command(self, tool_context):
        patch = {"capture_interval_seconds": 600, "motion_sensitivity": "high"}
        result = apply_config_patch(tool_context, "e2e-node-01", patch, approval_id="approval-abc")
        assert result["ok"] is True
        assert result["queued"] is True
        assert result["command_id"].startswith("cmd-config-")
        assert "capture_interval_seconds" in result["patch_keys"]
        assert result["approval_id"] == "approval-abc"

    def test_apply_config_patch_rejects_protected_keys(self, tool_context):
        with pytest.raises(ValueError, match="protected keys"):
            apply_config_patch(tool_context, "e2e-node-01", {"device_id": "hacked"})

    def test_apply_config_patch_unknown_device(self, tool_context):
        result = apply_config_patch(tool_context, "ghost-node", {"foo": "bar"})
        assert result["ok"] is False

    def test_list_pending_commands_returns_queued(self, tool_context):
        capture_now(tool_context, "e2e-node-01", reason="first")
        capture_now(tool_context, "e2e-node-01", reason="second")
        result = list_pending_commands(tool_context, device_id="e2e-node-01", status="queued")
        assert result["ok"] is True
        assert result["count"] >= 2
        assert all(c["status"] == "queued" for c in result["commands"])


# ── Layer 4: MCP stdio bridge ─────────────────────────────────────────────

class TestMCPStdioBridge:
    """Test the gateway's JSON-RPC stdio bridge directly via subprocess."""

    def _send_recv(self, proc, method, params=None, req_id=1):
        import subprocess
        request = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            request["params"] = params
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    @pytest.fixture()
    def bridge_proc(self, populated_db):
        import subprocess
        _, db_path = populated_db
        proc = subprocess.Popen(
            [sys.executable, "-m", "clawcam_gateway.mcp_server.stdio_server", "--db", str(db_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=GATEWAY_DIR,
            env=self._env(),
        )
        yield proc
        proc.stdin.close()
        proc.wait(timeout=5)

    def _env(self):
        import os
        env = os.environ.copy()
        env["PYTHONPATH"] = str(GATEWAY_DIR)
        return env

    def test_initialize(self, bridge_proc):
        resp = self._send_recv(bridge_proc, "initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "test", "version": "0"},
            "capabilities": {},
        })
        assert resp["result"]["serverInfo"]["name"] == "clawcam-gateway"
        assert "tools" in resp["result"]["capabilities"]

    def test_tools_list_includes_all_tools(self, bridge_proc):
        self._send_recv(bridge_proc, "initialize", {"protocolVersion": "2024-11-05", "clientInfo": {}, "capabilities": {}})
        resp = self._send_recv(bridge_proc, "tools/list", req_id=2)
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "get_recent_detections" in names
        assert "get_node_health" in names
        assert "generate_daily_summary" in names
        assert "list_pending_commands" in names
        assert "capture_now" in names
        assert "apply_config_patch" in names

    def test_tools_call_get_recent_detections(self, bridge_proc):
        self._send_recv(bridge_proc, "initialize", {"protocolVersion": "2024-11-05", "clientInfo": {}, "capabilities": {}})
        resp = self._send_recv(bridge_proc, "tools/call",
                               {"name": "get_recent_detections", "arguments": {"limit": 5}},
                               req_id=2)
        content = resp["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data["ok"] is True
        assert len(data["detections"]) == 1

    def test_tools_call_capture_now_queues(self, bridge_proc):
        self._send_recv(bridge_proc, "initialize", {"protocolVersion": "2024-11-05", "clientInfo": {}, "capabilities": {}})
        resp = self._send_recv(bridge_proc, "tools/call",
                               {"name": "capture_now", "arguments": {"device_id": "e2e-node-01", "reason": "mcp test"}},
                               req_id=2)
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["ok"] is True
        assert data["queued"] is True

    def test_ping(self, bridge_proc):
        self._send_recv(bridge_proc, "initialize", {"protocolVersion": "2024-11-05", "clientInfo": {}, "capabilities": {}})
        resp = self._send_recv(bridge_proc, "ping", req_id=2)
        assert resp["result"] == {}


# ── Layer 5: Brain adapter ────────────────────────────────────────────────

class TestBrainAdapter:
    def test_connect_discovers_tools(self, populated_db):
        _, db_path = populated_db
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            tools = adapter.list_tools()
        names = {t["name"] for t in tools}
        assert "get_recent_detections" in names
        assert "capture_now" in names

    def test_auto_approved_tools_call_without_flag(self, populated_db):
        _, db_path = populated_db
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            result = adapter.call_tool("get_recent_detections", {"limit": 5})
        assert result["ok"] is True
        assert len(result["detections"]) == 1

    def test_approval_gated_tool_raises_without_flag(self, populated_db):
        _, db_path = populated_db
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            with pytest.raises(ApprovalRequired) as exc_info:
                adapter.call_tool("capture_now", {"device_id": "e2e-node-01"})
        assert exc_info.value.tool_name == "capture_now"

    def test_approval_gated_tool_succeeds_with_flag(self, populated_db):
        _, db_path = populated_db
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            result = adapter.call_tool(
                "capture_now",
                {"device_id": "e2e-node-01", "reason": "approved by user"},
                approved=True,
            )
        assert result["ok"] is True
        assert result["queued"] is True

    def test_config_patch_approved(self, populated_db):
        _, db_path = populated_db
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            result = adapter.call_tool(
                "apply_config_patch",
                {"device_id": "e2e-node-01", "patch": {"motion_sensitivity": "medium"}},
                approved=True,
            )
        assert result["ok"] is True
        assert result["queued"] is True

    def test_ping(self, populated_db):
        _, db_path = populated_db
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            assert adapter.ping() is True

    def test_as_obc_tool_entries(self, populated_db):
        _, db_path = populated_db
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            entries = adapter.as_obc_tool_entries()
        capture_entry = next(e for e in entries if e["name"] == "capture_now")
        assert capture_entry["approval_required"] is True
        assert capture_entry["source"] == "clawcam-gateway"

        detection_entry = next(e for e in entries if e["name"] == "get_recent_detections")
        assert detection_entry["approval_required"] is False

    def test_policy_summary_matches_definitions(self, populated_db):
        """Verify that all tools discovered are classified by the policy."""
        _, db_path = populated_db
        default_policy = ToolPolicy()
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            tools = adapter.list_tools()
        for tool in tools:
            name = tool["name"]
            # Every tool must be in exactly one policy bucket
            in_auto = default_policy.is_auto_approved(name)
            in_ask = default_policy.requires_approval(name)
            assert in_auto or in_ask, f"tool '{name}' is not classified in any policy bucket"
            assert not (in_auto and in_ask), f"tool '{name}' is in both policy buckets"


# ── Full end-to-end flow ───────────────────────────────────────────────────

class TestFullPhase1Flow:
    """Single test that exercises every layer in sequence."""

    def test_phase1_complete_flow(self, tmp_path):
        # 1. Simulator generates bundle
        node = SimulatedNode(device_id="flow-node", deployment_id="flow-deploy", name="Flow Camera")
        bundle_dir = tmp_path / "bundle"
        node.write_bundle(bundle_dir, EVENT_DATE)

        # 2. Import into gateway database
        db_path = tmp_path / "gw.db"
        db = GatewayDatabase(db_path)
        imported = import_directory(bundle_dir, db)
        assert len(imported) == 3

        # 3. Python tools verify data
        ctx = ToolContext(database_path=db_path)
        detections = get_recent_detections(ctx, limit=10)
        assert detections["ok"] and len(detections["detections"]) == 1

        health = get_node_health(ctx, "flow-node")
        assert health["ok"]

        summary = generate_daily_summary(ctx, report_date="2026-05-12")
        assert summary["ok"] and summary["event_count"] == 1

        # 4. Approval-gated tools queue commands (simulating brain-approved call)
        cap = capture_now(ctx, "flow-node", reason="scheduled check")
        assert cap["ok"] and cap["queued"]

        patch_result = apply_config_patch(
            ctx, "flow-node",
            {"capture_interval_seconds": 300},
            approval_id="approval-e2e-001",
        )
        assert patch_result["ok"] and patch_result["queued"]

        pending = list_pending_commands(ctx, device_id="flow-node", status="queued")
        assert pending["ok"] and pending["count"] == 2

        # 5. Brain adapter end-to-end (reads, approval enforcement, approved call)
        with ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=db_path) as adapter:
            assert adapter.ping()

            read_result = adapter.call_tool("get_recent_detections", {"limit": 5})
            assert read_result["ok"] and len(read_result["detections"]) == 1

            with pytest.raises(ApprovalRequired):
                adapter.call_tool("capture_now", {"device_id": "flow-node"})

            approved_result = adapter.call_tool(
                "capture_now",
                {"device_id": "flow-node", "reason": "end-to-end validation"},
                approved=True,
            )
            assert approved_result["ok"] and approved_result["queued"]
