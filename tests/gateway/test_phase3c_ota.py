"""Phase 3C tests — OTA firmware update pipeline.

Covers:
  - Firmware upload REST endpoint (POST /api/v1/firmware)
  - Firmware metadata and download endpoints
  - GatewayDatabase firmware_builds CRUD
  - queue_firmware_update MCP tool (happy path + error cases)
  - list_firmware_builds MCP tool
  - Brain adapter policy: list_firmware_builds auto-approved, queue_firmware_update gated
"""
from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools.clawcam_tools import (
    ToolContext,
    list_firmware_builds,
    queue_firmware_update,
)

# Add brain adapter directory to path for ToolPolicy import
_BRAIN_DIR = Path(__file__).parents[2] / "brain" / "oh-ben-claw-adapter"
if str(_BRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BRAIN_DIR))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "ota_test.db")
    # Register a device that supports OTA
    db.upsert_device({
        "device_id": "node-ota-001",
        "device_type": "node",
        "name": "OTA Test Node",
        "status": "active",
        "capabilities": [
            "cap_clawcam_camera_trap",
            "cap_clawcam_events",
            "cap_clawcam_firmware_ota",
        ],
        "created_at": "2026-05-13T00:00:00Z",
        "last_seen_at": "2026-05-13T00:00:00Z",
    })
    # Register a device WITHOUT OTA capability
    db.upsert_device({
        "device_id": "node-no-ota",
        "device_type": "node",
        "name": "Non-OTA Node",
        "status": "active",
        "capabilities": ["cap_clawcam_camera_trap"],
        "created_at": "2026-05-13T00:00:00Z",
        "last_seen_at": "2026-05-13T00:00:00Z",
    })
    return db


@pytest.fixture()
def ctx(tmp_db) -> ToolContext:
    return ToolContext(database_path=tmp_db.path, mqtt_bridge=None)


@pytest.fixture()
def client(tmp_path, tmp_db) -> TestClient:
    config = GatewayConfig(
        database_path=str(tmp_db.path),
        media_dir=tmp_path / "media",
        mqtt_enabled=False,
    )
    app = create_app(config)
    return TestClient(app)


FAKE_FIRMWARE = b"\x00\x01\x02\x03" * 256  # 1 KiB fake binary
FAKE_SHA256 = hashlib.sha256(FAKE_FIRMWARE).hexdigest()


# ── Database CRUD ─────────────────────────────────────────────────────────────

class TestFirmwareBuildsCRUD:
    def test_add_and_get_build(self, tmp_db):
        tmp_db.add_firmware_build("build-001", "0.2.0", "build-001_fw.bin", FAKE_SHA256, 1024)
        build = tmp_db.get_firmware_build("build-001")
        assert build is not None
        assert build["build_id"] == "build-001"
        assert build["version"] == "0.2.0"
        assert build["sha256"] == FAKE_SHA256
        assert build["size_bytes"] == 1024

    def test_get_unknown_build_returns_none(self, tmp_db):
        assert tmp_db.get_firmware_build("does-not-exist") is None

    def test_list_builds_empty(self, tmp_db):
        assert tmp_db.list_firmware_builds() == []

    def test_list_builds_ordered_newest_first(self, tmp_db):
        tmp_db.add_firmware_build("b-001", "0.1.0", "b001.bin", "aaa", 100)
        tmp_db.add_firmware_build("b-002", "0.2.0", "b002.bin", "bbb", 200)
        builds = tmp_db.list_firmware_builds()
        assert len(builds) == 2
        # Most recently uploaded first
        assert builds[0]["build_id"] == "b-002"
        assert builds[1]["build_id"] == "b-001"


# ── REST endpoints ────────────────────────────────────────────────────────────

class TestFirmwareUploadEndpoint:
    def test_upload_returns_build_id_and_sha256(self, client):
        response = client.post(
            "/api/v1/firmware",
            files={"file": ("clawcam-node-0.2.0.bin", io.BytesIO(FAKE_FIRMWARE), "application/octet-stream")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "build_id" in data
        assert data["sha256"] == FAKE_SHA256
        assert data["size_bytes"] == len(FAKE_FIRMWARE)
        assert data["version"] == "0.2.0"
        assert "/api/v1/firmware/" in data["download_url"]

    def test_upload_empty_file_returns_400(self, client):
        response = client.post(
            "/api/v1/firmware",
            files={"file": ("empty.bin", io.BytesIO(b""), "application/octet-stream")},
        )
        assert response.status_code == 400

    def test_upload_stores_file_on_disk(self, client, tmp_path):
        client.post(
            "/api/v1/firmware",
            files={"file": ("fw.bin", io.BytesIO(FAKE_FIRMWARE), "application/octet-stream")},
        )
        # Media dir for this client fixture is tmp_path / "media"
        fw_files = list((tmp_path / "media" / "firmware").glob("*.bin"))
        assert len(fw_files) == 1
        assert fw_files[0].read_bytes() == FAKE_FIRMWARE


class TestFirmwareListEndpoint:
    def test_list_returns_empty_initially(self, client):
        response = client.get("/api/v1/firmware")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["builds"] == []
        assert data["count"] == 0

    def test_list_after_upload(self, client):
        client.post(
            "/api/v1/firmware",
            files={"file": ("fw-0.3.0.bin", io.BytesIO(FAKE_FIRMWARE), "application/octet-stream")},
        )
        response = client.get("/api/v1/firmware")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["builds"][0]["version"] == "0.3.0"


class TestFirmwareGetEndpoint:
    def test_get_existing_build(self, client):
        upload = client.post(
            "/api/v1/firmware",
            files={"file": ("fw.bin", io.BytesIO(FAKE_FIRMWARE), "application/octet-stream")},
        )
        build_id = upload.json()["build_id"]
        response = client.get(f"/api/v1/firmware/{build_id}")
        assert response.status_code == 200
        assert response.json()["build"]["build_id"] == build_id

    def test_get_unknown_build_returns_404(self, client):
        response = client.get("/api/v1/firmware/does-not-exist")
        assert response.status_code == 404


class TestFirmwareDownloadEndpoint:
    def test_download_returns_binary(self, client):
        upload = client.post(
            "/api/v1/firmware",
            files={"file": ("fw.bin", io.BytesIO(FAKE_FIRMWARE), "application/octet-stream")},
        )
        build_id = upload.json()["build_id"]
        response = client.get(f"/api/v1/firmware/{build_id}/download")
        assert response.status_code == 200
        assert response.content == FAKE_FIRMWARE
        assert response.headers["content-type"] == "application/octet-stream"

    def test_download_unknown_build_returns_404(self, client):
        response = client.get("/api/v1/firmware/unknown-id/download")
        assert response.status_code == 404


# ── Tool functions ────────────────────────────────────────────────────────────

class TestListFirmwareBuilds:
    def test_empty_list(self, ctx):
        result = list_firmware_builds(ctx)
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["builds"] == []

    def test_returns_all_builds(self, ctx, tmp_db):
        tmp_db.add_firmware_build("b-a", "0.1.0", "a.bin", "aaa", 100)
        tmp_db.add_firmware_build("b-b", "0.2.0", "b.bin", "bbb", 200)
        result = list_firmware_builds(ctx)
        assert result["ok"] is True
        assert result["count"] == 2


class TestQueueFirmwareUpdate:
    def _add_build(self, tmp_db, build_id="bld-001", version="0.3.0") -> str:
        tmp_db.add_firmware_build(build_id, version, f"{build_id}.bin", FAKE_SHA256, 1024)
        return build_id

    def test_happy_path_queues_command(self, ctx, tmp_db):
        build_id = self._add_build(tmp_db)
        result = queue_firmware_update(ctx, "node-ota-001", build_id)
        assert result["ok"] is True
        assert result["queued"] is True
        assert result["build_id"] == build_id
        assert result["version"] == "0.3.0"
        assert result["sha256"] == FAKE_SHA256
        assert result["status"] == "queued"
        assert "mqtt_pushed" in result

    def test_command_stored_in_db(self, ctx, tmp_db):
        build_id = self._add_build(tmp_db)
        result = queue_firmware_update(ctx, "node-ota-001", build_id)
        command_id = result["command_id"]
        stored = tmp_db.get_pending_command(command_id)
        assert stored is not None
        assert stored["command_type"] == "firmware_update"
        assert stored["device_id"] == "node-ota-001"
        assert stored["build_id"] == build_id
        assert stored["sha256"] == FAKE_SHA256
        assert "/api/v1/firmware/" in stored["firmware_url"]

    def test_unknown_device_returns_error(self, ctx, tmp_db):
        build_id = self._add_build(tmp_db)
        result = queue_firmware_update(ctx, "node-ghost", build_id)
        assert result["ok"] is False
        assert "unknown device" in result["error"]

    def test_unknown_build_id_returns_error(self, ctx):
        result = queue_firmware_update(ctx, "node-ota-001", "nonexistent-build")
        assert result["ok"] is False
        assert "unknown build_id" in result["error"]

    def test_device_without_ota_capability_rejected(self, ctx, tmp_db):
        build_id = self._add_build(tmp_db)
        result = queue_firmware_update(ctx, "node-no-ota", build_id)
        assert result["ok"] is False
        assert "cap_clawcam_firmware_ota" in result["error"]
        assert "capabilities" in result

    def test_mqtt_pushed_false_when_no_bridge(self, ctx, tmp_db):
        build_id = self._add_build(tmp_db)
        result = queue_firmware_update(ctx, "node-ota-001", build_id)
        assert result["mqtt_pushed"] is False

    def test_mqtt_pushed_true_when_bridge_available(self, tmp_db):
        from unittest.mock import MagicMock
        mock_bridge = MagicMock()
        mock_bridge.publish_command.return_value = True
        ctx = ToolContext(database_path=tmp_db.path, mqtt_bridge=mock_bridge)
        build_id = self._add_build(tmp_db)
        result = queue_firmware_update(ctx, "node-ota-001", build_id)
        assert result["mqtt_pushed"] is True
        mock_bridge.publish_command.assert_called_once()


# ── Tool dispatch ─────────────────────────────────────────────────────────────

class TestOTAToolDispatch:
    def test_list_firmware_builds_via_dispatch(self, tmp_db):
        from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
        result = dispatch_tool("list_firmware_builds", {}, database_path=tmp_db.path)
        assert result["ok"] is True
        assert "builds" in result

    def test_queue_firmware_update_via_dispatch(self, tmp_db):
        from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
        tmp_db.add_firmware_build("d-001", "0.4.0", "d001.bin", FAKE_SHA256, 512)
        result = dispatch_tool(
            "queue_firmware_update",
            {"device_id": "node-ota-001", "build_id": "d-001"},
            database_path=tmp_db.path,
        )
        assert result["ok"] is True
        assert result["version"] == "0.4.0"

    def test_unknown_tool_returns_error(self, tmp_db):
        from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
        result = dispatch_tool("no_such_tool", {}, database_path=tmp_db.path)
        assert result["ok"] is False
        assert "unknown" in result["error"]


# ── Brain adapter policy ──────────────────────────────────────────────────────

class TestBrainAdapterOTAPolicy:
    def test_list_firmware_builds_is_auto_approved(self):
        from clawcam_adapter import ToolPolicy
        policy = ToolPolicy()
        assert policy.is_auto_approved("list_firmware_builds") is True
        assert policy.requires_approval("list_firmware_builds") is False

    def test_queue_firmware_update_requires_approval(self):
        from clawcam_adapter import ToolPolicy
        policy = ToolPolicy()
        assert policy.requires_approval("queue_firmware_update") is True
        assert policy.is_auto_approved("queue_firmware_update") is False
