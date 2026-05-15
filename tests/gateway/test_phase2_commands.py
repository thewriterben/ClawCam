"""Phase 2 tests — command polling, ack, capabilities, and command lifecycle."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.storage.database import GatewayDatabase


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def app_and_db(tmp_path):
    config = GatewayConfig(
        database_path=tmp_path / "gateway.db",
        media_dir=tmp_path / "media",
    )
    app = create_app(config)
    db = GatewayDatabase(config.database_path)
    return TestClient(app), db


@pytest.fixture()
def registered_device(app_and_db):
    """Register a device with camera-trap capability and return (client, db, device_id)."""
    client, db = app_and_db
    device_id = "node-phase2-001"
    device = {
        "device_id": device_id,
        "device_type": "node",
        "name": "Phase 2 Test Node",
        "status": "active",
        "capabilities": [
            "cap_clawcam_camera_trap",
            "cap_clawcam_power",
            "cap_clawcam_storage",
            "cap_clawcam_events",
        ],
        "created_at": "2026-05-13T00:00:00Z",
        "last_seen_at": "2026-05-13T00:00:00Z",
    }
    resp = client.post("/api/v1/devices", json={"data": device})
    assert resp.status_code == 200, resp.text
    return client, db, device_id


# ── Capabilities endpoint ─────────────────────────────────────────────────────

class TestCapabilitiesEndpoint:
    def test_get_capabilities_returns_list(self, registered_device):
        client, db, device_id = registered_device
        resp = client.get(f"/api/v1/devices/{device_id}/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert "capabilities" in data
        assert "cap_clawcam_camera_trap" in data["capabilities"]

    def test_get_capabilities_flags(self, registered_device):
        """Verify capability groups are returned for downstream `has_X` derivation."""
        client, db, device_id = registered_device
        resp = client.get(f"/api/v1/devices/{device_id}/capabilities")
        data = resp.json()
        caps = data["capabilities"]
        assert "cap_clawcam_camera_trap" in caps
        assert "cap_clawcam_power" in caps
        assert "cap_clawcam_storage" in caps
        assert "cap_clawcam_events" in caps
        assert "cap_clawcam_sensors" not in caps

    def test_get_capabilities_unknown_device(self, app_and_db):
        client, db = app_and_db
        resp = client.get("/api/v1/devices/no-such-device/capabilities")
        assert resp.status_code == 404


# ── Command polling endpoint ──────────────────────────────────────────────────

class TestCommandPollingEndpoint:
    def test_poll_empty_queue_returns_zero(self, registered_device):
        client, db, device_id = registered_device
        resp = client.get(f"/api/v1/commands/{device_id}/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["commands"] == []

    def test_poll_unknown_device_returns_404(self, app_and_db):
        client, db = app_and_db
        resp = client.get("/api/v1/commands/no-such-device/pending")
        assert resp.status_code == 404

    def test_poll_returns_queued_command(self, registered_device):
        client, db, device_id = registered_device
        db.add_pending_command({
            "command_id": "cmd-test-001",
            "command_type": "capture_now",
            "device_id": device_id,
            "status": "queued",
            "reason": "test",
        })
        cmd_id = "cmd-test-001"
        resp = client.get(f"/api/v1/commands/{device_id}/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        cmd = data["commands"][0]
        assert cmd["command_id"] == "cmd-test-001"
        assert cmd["command_type"] == "capture_now"

    def test_poll_marks_commands_as_delivered(self, registered_device):
        client, db, device_id = registered_device
        db.add_pending_command({
            "command_id": "cmd-test-002",
            "command_type": "capture_now",
            "device_id": device_id,
            "status": "queued",
            "reason": "delivery check",
        })
        client.get(f"/api/v1/commands/{device_id}/pending")

        # Second poll should return empty — already delivered
        resp2 = client.get(f"/api/v1/commands/{device_id}/pending")
        assert resp2.json()["count"] == 0

    def test_poll_respects_limit_param(self, registered_device):
        client, db, device_id = registered_device
        for i in range(4):
            db.add_pending_command({
                "command_id": f"cmd-limit-{i:03d}",
                "command_type": "capture_now",
                "device_id": device_id,
                "status": "queued",
                "reason": f"batch {i}",
            })
        resp = client.get(f"/api/v1/commands/{device_id}/pending?limit=2")
        assert resp.json()["count"] == 2


# ── Ack endpoint ──────────────────────────────────────────────────────────────

class TestAckEndpoint:
    def _queue_command(self, db, device_id, cmd_id="cmd-ack-001"):
        db.add_pending_command({
            "command_id": cmd_id,
            "command_type": "capture_now",
            "device_id": device_id,
            "status": "queued",
            "reason": "ack test",
        })
        return cmd_id

    def test_ack_executed(self, registered_device):
        client, db, device_id = registered_device
        cmd_id = self._queue_command(db, device_id)
        resp = client.post(
            f"/api/v1/commands/{cmd_id}/ack",
            json={"status": "executed", "result": {"message": "capture completed"}},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_ack_failed(self, registered_device):
        client, db, device_id = registered_device
        cmd_id = self._queue_command(db, device_id, "cmd-ack-002")
        resp = client.post(
            f"/api/v1/commands/{cmd_id}/ack",
            json={"status": "failed", "result": {"message": "no camera handler"}},
        )
        assert resp.status_code == 200

    def test_ack_skipped(self, registered_device):
        client, db, device_id = registered_device
        cmd_id = self._queue_command(db, device_id, "cmd-ack-003")
        resp = client.post(
            f"/api/v1/commands/{cmd_id}/ack",
            json={"status": "skipped"},
        )
        assert resp.status_code == 200

    def test_ack_invalid_status_rejected(self, registered_device):
        client, db, device_id = registered_device
        cmd_id = self._queue_command(db, device_id, "cmd-ack-004")
        resp = client.post(
            f"/api/v1/commands/{cmd_id}/ack",
            json={"status": "invalid_status"},
        )
        # 400 from the handler's explicit allowlist check; 422 would come from pydantic.
        assert resp.status_code in (400, 422)

    def test_ack_unknown_command_returns_404(self, app_and_db):
        client, db = app_and_db
        resp = client.post(
            "/api/v1/commands/cmd-does-not-exist/ack",
            json={"status": "executed"},
        )
        assert resp.status_code == 404


# ── Full command lifecycle integration ────────────────────────────────────────

class TestCommandLifecycle:
    """Simulates the full node wake cycle: queue → poll → ack."""

    def test_capture_now_lifecycle(self, registered_device):
        client, db, device_id = registered_device

        # Brain queues capture_now via MCP tool (simulated directly here)
        queue_resp = client.post("/api/v1/tools/capture_now", json={
            "arguments": {"device_id": device_id, "reason": "lifecycle test"},
        })
        assert queue_resp.status_code == 200
        result = queue_resp.json()
        assert result.get("ok") is True
        command_id = result["command_id"]

        # Node wakes and polls
        poll_resp = client.get(f"/api/v1/commands/{device_id}/pending")
        assert poll_resp.status_code == 200
        poll_data = poll_resp.json()
        assert poll_data["count"] == 1
        assert poll_data["commands"][0]["command_id"] == command_id

        # Node executes and acks
        ack_resp = client.post(
            f"/api/v1/commands/{command_id}/ack",
            json={"status": "executed", "result": {"message": "capture completed", "node": device_id}},
        )
        assert ack_resp.status_code == 200
        assert ack_resp.json()["ok"] is True

        # Subsequent poll shows empty queue
        poll2 = client.get(f"/api/v1/commands/{device_id}/pending")
        assert poll2.json()["count"] == 0

    def test_apply_config_patch_lifecycle(self, registered_device):
        client, db, device_id = registered_device

        # Queue apply_config_patch via tool endpoint (approval bypassed in test)
        queue_resp = client.post("/api/v1/tools/apply_config_patch", json={
            "arguments": {
                "device_id": device_id,
                "patch": {"capture_interval_seconds": 600},
                "approval_id": "approval-12345",
            },
        })
        assert queue_resp.status_code == 200
        result = queue_resp.json()
        assert result.get("ok") is True
        command_id = result["command_id"]

        # Node polls, gets the config patch command
        poll_resp = client.get(f"/api/v1/commands/{device_id}/pending")
        cmds = poll_resp.json()["commands"]
        assert len(cmds) == 1
        cmd = cmds[0]
        assert cmd["command_type"] == "apply_config_patch"
        assert cmd["command_id"] == command_id

        # Node applies patch and acks
        ack_resp = client.post(
            f"/api/v1/commands/{command_id}/ack",
            json={"status": "executed", "result": {"message": "config patch applied and saved to NVS"}},
        )
        assert ack_resp.status_code == 200

    def test_no_capability_blocks_capture_command(self, app_and_db):
        """Device without cap_clawcam_camera_trap should get an error, not a queued command."""
        client, db = app_and_db
        device_id = "node-no-caps"
        device = {
            "device_id": device_id,
            "device_type": "node",
            "name": "No-Caps Node",
            "status": "active",
            "capabilities": ["cap_clawcam_power"],  # no camera_trap
            "created_at": "2026-05-13T00:00:00Z",
            "last_seen_at": "2026-05-13T00:00:00Z",
        }
        client.post("/api/v1/devices", json={"data": device})

        resp = client.post("/api/v1/tools/capture_now", json={
            "arguments": {"device_id": device_id},
        })
        assert resp.status_code == 200
        data = resp.json()
        # Tool returns an error result, not a queued command
        assert data.get("ok") is not True or "error" in data


# ── GatewayDatabase-level command tracking ──────────────────────────────────────────

class TestGatewayDatabaseCommandTracking:
    def test_add_and_list_pending(self, app_and_db):
        client, db = app_and_db
        db.add_pending_command({"command_id": "cmd-db-001", "command_type": "capture_now",
                                 "device_id": "node-x", "status": "queued", "reason": "db test"})
        cmds = db.list_pending_commands("node-x", status="queued")
        assert len(cmds) == 1
        assert cmds[0]["command_id"] == "cmd-db-001"

    def test_update_status_to_executed(self, app_and_db):
        client, db = app_and_db
        db.add_pending_command({"command_id": "cmd-db-002", "command_type": "capture_now",
                                 "device_id": "node-x", "status": "queued"})
        db.update_command_status("cmd-db-002", "executed", result={"message": "done"})
        # After update, should no longer appear in "queued" list
        queued = db.list_pending_commands("node-x", status="queued")
        assert all(c["command_id"] != "cmd-db-002" for c in queued)

    def test_get_pending_command_by_id(self, app_and_db):
        client, db = app_and_db
        db.add_pending_command({"command_id": "cmd-db-003", "command_type": "apply_config_patch",
                                 "device_id": "node-y", "status": "queued",
                                 "patch": {"capture_interval_seconds": 120}})
        cmd = db.get_pending_command("cmd-db-003")
        assert cmd is not None
        assert cmd["command_type"] == "apply_config_patch"
