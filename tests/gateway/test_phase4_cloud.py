"""Phase 4 tests — cloud storage backend.

Covers:
  - BaseCloudStore / NoopStore / S3Store / GCSStore availability and contract
  - CloudUploadWorker: happy path, missing file, upload error, DB persistence
  - GatewayDatabase cloud_uploads CRUD and summary
  - GET /api/v1/cloud/uploads REST endpoint
  - POST /api/v1/media triggers cloud upload background task
  - get_cloud_sync_status MCP tool
  - Brain adapter policy: get_cloud_sync_status auto-approved
  - GatewayConfig: cloud env-var parsing
  - get_cloud_store factory
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import io

import pytest
from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.sync.cloud_store import (
    BaseCloudStore,
    GCSStore,
    NoopStore,
    S3Store,
    get_cloud_store,
)
from clawcam_gateway.sync.upload_worker import CloudUploadWorker
from clawcam_gateway.tools.clawcam_tools import ToolContext, get_cloud_sync_status

_BRAIN_DIR = Path(__file__).parents[2] / "brain" / "oh-ben-claw-adapter"
if str(_BRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BRAIN_DIR))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "cloud_test.db")
    db.upsert_device({
        "device_id": "node-cloud-001",
        "device_type": "node",
        "name": "Cloud Test Node",
        "status": "active",
        "capabilities": ["cap_clawcam_camera_trap", "cap_clawcam_events"],
        "created_at": "2026-05-14T00:00:00Z",
        "last_seen_at": "2026-05-14T00:00:00Z",
    })
    db.add_event({
        "event_id": "evt-cloud-001",
        "event_type": "capture",
        "device_id": "node-cloud-001",
        "timestamp": "2026-05-14T06:00:00Z",
        "time_source": "rtc",
        "source": "field",
    })
    return db


@pytest.fixture()
def noop_store() -> NoopStore:
    return NoopStore()


@pytest.fixture()
def worker(tmp_db, noop_store) -> CloudUploadWorker:
    return CloudUploadWorker(db=tmp_db, store=noop_store)


@pytest.fixture()
def fake_image(tmp_path) -> Path:
    p = tmp_path / "evt-cloud-001.jpg"
    p.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    return p


@pytest.fixture()
def ctx(tmp_db) -> ToolContext:
    return ToolContext(database_path=tmp_db.path, mqtt_bridge=None)


@pytest.fixture()
def client(tmp_path, tmp_db) -> TestClient:
    config = GatewayConfig(
        database_path=str(tmp_db.path),
        media_dir=tmp_path / "media",
        mqtt_enabled=False,
        cloud_enabled=False,  # noop — tests can verify tracking still works
    )
    app = create_app(config)
    return TestClient(app)


# ── NoopStore ─────────────────────────────────────────────────────────────────

class TestNoopStore:
    def test_provider(self):
        assert NoopStore().provider == "noop"

    def test_is_available(self):
        assert NoopStore().is_available() is True

    def test_upload_returns_noop_uri(self, tmp_path):
        p = tmp_path / "test.jpg"
        p.write_bytes(b"fake")
        uri = NoopStore().upload(p, "events/test.jpg")
        assert uri == "noop://events/test.jpg"

    def test_upload_missing_file_succeeds(self, tmp_path):
        # NoopStore doesn't check existence
        uri = NoopStore().upload(tmp_path / "missing.jpg", "missing.jpg")
        assert "noop://" in uri


# ── S3Store unit ──────────────────────────────────────────────────────────────

class TestS3Store:
    def test_provider(self):
        assert S3Store(bucket="my-bucket").provider == "s3"

    def test_is_available_without_boto3(self):
        with patch.dict("sys.modules", {"boto3": None}):
            store = S3Store(bucket="")
            # empty bucket → False even if boto3 were available
            assert store.is_available() is False

    def test_is_available_with_boto3_and_bucket(self):
        mock_boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            store = S3Store(bucket="my-bucket")
            assert store.is_available() is True

    def test_upload_calls_boto3_upload_file(self, tmp_path):
        p = tmp_path / "img.jpg"
        p.write_bytes(b"image")
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            store = S3Store(bucket="test-bucket", prefix="clawcam/")
            uri = store.upload(p, "evt-001/img.jpg")
        assert uri == "s3://test-bucket/clawcam/evt-001/img.jpg"
        mock_client.upload_file.assert_called_once()

    def test_upload_raises_when_boto3_missing(self, tmp_path):
        p = tmp_path / "img.jpg"
        p.write_bytes(b"image")
        with patch.dict("sys.modules", {"boto3": None}):
            store = S3Store(bucket="b")
            with pytest.raises(RuntimeError, match="boto3"):
                store.upload(p, "key")

    def test_custom_endpoint_passed_to_boto3(self, tmp_path):
        p = tmp_path / "img.jpg"
        p.write_bytes(b"image")
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            store = S3Store(bucket="b", endpoint_url="http://localhost:9000")
            store.upload(p, "k")
        _, kwargs = mock_boto3.client.call_args
        assert kwargs.get("endpoint_url") == "http://localhost:9000"


# ── GCSStore unit ─────────────────────────────────────────────────────────────

class TestGCSStore:
    def test_provider(self):
        assert GCSStore(bucket="my-bucket").provider == "gcs"

    def test_is_available_without_google_cloud(self):
        with patch.dict("sys.modules", {"google": None, "google.cloud": None, "google.cloud.storage": None}):
            store = GCSStore(bucket="")
            assert store.is_available() is False

    def test_upload_raises_when_google_cloud_missing(self, tmp_path):
        p = tmp_path / "img.jpg"
        p.write_bytes(b"image")
        gcs_modules = {
            "google": MagicMock(),
            "google.cloud": None,
            "google.cloud.storage": None,
        }
        with patch.dict("sys.modules", gcs_modules):
            store = GCSStore(bucket="b")
            with pytest.raises(RuntimeError, match="google-cloud-storage"):
                store.upload(p, "key")


# ── get_cloud_store factory ───────────────────────────────────────────────────

class TestGetCloudStoreFactory:
    def test_disabled_returns_noop(self):
        config = GatewayConfig(cloud_enabled=False, cloud_provider="s3", cloud_bucket="b")
        store = get_cloud_store(config)
        assert isinstance(store, NoopStore)

    def test_s3_provider_returns_s3_store(self):
        config = GatewayConfig(cloud_enabled=True, cloud_provider="s3", cloud_bucket="bucket")
        store = get_cloud_store(config)
        assert isinstance(store, S3Store)

    def test_gcs_provider_returns_gcs_store(self):
        config = GatewayConfig(cloud_enabled=True, cloud_provider="gcs", cloud_bucket="bucket")
        store = get_cloud_store(config)
        assert isinstance(store, GCSStore)

    def test_unknown_provider_returns_noop(self):
        config = GatewayConfig(cloud_enabled=True, cloud_provider="azure", cloud_bucket="bucket")
        store = get_cloud_store(config)
        assert isinstance(store, NoopStore)

    def test_noop_provider_explicit(self):
        config = GatewayConfig(cloud_enabled=True, cloud_provider="noop", cloud_bucket="")
        store = get_cloud_store(config)
        assert isinstance(store, NoopStore)


# ── CloudUploadWorker ─────────────────────────────────────────────────────────

class TestCloudUploadWorker:
    def test_happy_path_uploaded_status(self, worker, tmp_db, fake_image):
        result = worker.queue_and_upload(fake_image, event_id="evt-cloud-001")
        assert result["status"] == "uploaded"
        assert result["remote_uri"] is not None
        assert result["error"] is None

    def test_happy_path_record_in_db(self, worker, tmp_db, fake_image):
        result = worker.queue_and_upload(fake_image, event_id="evt-cloud-001")
        uploads = tmp_db.list_cloud_uploads()
        assert len(uploads) == 1
        assert uploads[0]["status"] == "uploaded"
        assert uploads[0]["event_id"] == "evt-cloud-001"
        assert uploads[0]["provider"] == "noop"

    def test_missing_file_returns_failed(self, worker, tmp_path):
        missing = tmp_path / "does_not_exist.jpg"
        result = worker.queue_and_upload(missing, event_id="evt-cloud-001")
        assert result["status"] == "failed"
        assert "not found" in result["error"]

    def test_missing_file_recorded_as_failed_in_db(self, worker, tmp_db, tmp_path):
        missing = tmp_path / "missing.jpg"
        worker.queue_and_upload(missing, event_id="evt-cloud-001")
        uploads = tmp_db.list_cloud_uploads()
        assert uploads[0]["status"] == "failed"

    def test_store_error_returns_failed(self, tmp_db, tmp_path, fake_image):
        bad_store = MagicMock(spec=BaseCloudStore)
        bad_store.provider = "s3"
        bad_store.upload.side_effect = RuntimeError("network error")
        worker = CloudUploadWorker(db=tmp_db, store=bad_store)
        result = worker.queue_and_upload(fake_image, event_id="evt-cloud-001")
        assert result["status"] == "failed"
        assert "network error" in result["error"]

    def test_custom_remote_key_used(self, worker, tmp_db, fake_image):
        worker.queue_and_upload(fake_image, event_id="evt-cloud-001", remote_key="custom/path/img.jpg")
        uploads = tmp_db.list_cloud_uploads()
        assert uploads[0]["remote_uri"] == "noop://custom/path/img.jpg"

    def test_default_remote_key_includes_event_id(self, worker, tmp_db, fake_image):
        worker.queue_and_upload(fake_image, event_id="evt-cloud-001")
        uploads = tmp_db.list_cloud_uploads()
        assert "evt-cloud-001" in uploads[0]["remote_uri"]

    def test_no_event_id_uses_filename(self, worker, tmp_db, fake_image):
        worker.queue_and_upload(fake_image, event_id=None)
        uploads = tmp_db.list_cloud_uploads()
        assert fake_image.name in uploads[0]["remote_uri"]


# ── Database CRUD ─────────────────────────────────────────────────────────────

class TestCloudUploadDatabase:
    def test_add_and_list(self, tmp_db):
        uid = tmp_db.add_cloud_upload("evt-cloud-001", "/media/img.jpg", "noop")
        uploads = tmp_db.list_cloud_uploads()
        assert len(uploads) == 1
        assert uploads[0]["upload_id"] == uid
        assert uploads[0]["status"] == "pending"

    def test_update_to_uploaded(self, tmp_db):
        uid = tmp_db.add_cloud_upload("evt-cloud-001", "/media/img.jpg", "s3")
        tmp_db.update_cloud_upload(uid, "uploaded", remote_uri="s3://b/k", uploaded_at="2026-05-14T06:00:00Z")
        uploads = tmp_db.list_cloud_uploads()
        assert uploads[0]["status"] == "uploaded"
        assert uploads[0]["remote_uri"] == "s3://b/k"

    def test_update_to_failed(self, tmp_db):
        uid = tmp_db.add_cloud_upload(None, "/media/img.jpg", "gcs")
        tmp_db.update_cloud_upload(uid, "failed", error="network timeout")
        uploads = tmp_db.list_cloud_uploads()
        assert uploads[0]["status"] == "failed"
        assert uploads[0]["error"] == "network timeout"

    def test_filter_by_status(self, tmp_db):
        uid1 = tmp_db.add_cloud_upload("evt-cloud-001", "/a.jpg", "noop")
        uid2 = tmp_db.add_cloud_upload("evt-cloud-001", "/b.jpg", "noop")
        tmp_db.update_cloud_upload(uid1, "uploaded", remote_uri="noop://a.jpg")
        pending = tmp_db.list_cloud_uploads(status="pending")
        assert len(pending) == 1
        assert pending[0]["upload_id"] == uid2

    def test_summary_counts(self, tmp_db):
        u1 = tmp_db.add_cloud_upload("evt-cloud-001", "/a.jpg", "noop")
        u2 = tmp_db.add_cloud_upload("evt-cloud-001", "/b.jpg", "noop")
        tmp_db.update_cloud_upload(u1, "uploaded", remote_uri="noop://a")
        tmp_db.update_cloud_upload(u2, "failed", error="err")
        summary = tmp_db.get_cloud_upload_summary()
        assert summary.get("uploaded", 0) == 1
        assert summary.get("failed", 0) == 1

    def test_empty_summary(self, tmp_db):
        assert tmp_db.get_cloud_upload_summary() == {}


# ── REST endpoint ─────────────────────────────────────────────────────────────

class TestCloudUploadsEndpoint:
    def test_returns_empty_initially(self, client):
        response = client.get("/api/v1/cloud/uploads")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["uploads"] == []
        assert data["count"] == 0
        assert data["provider"] == "noop"
        assert data["cloud_enabled"] is False

    def test_returns_uploads_after_media_post(self, client, tmp_db):
        # POST a media file to trigger background cloud upload
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 50
        client.post(
            "/api/v1/media/evt-cloud-001",
            files={"file": ("img.jpg", io.BytesIO(fake_bytes), "image/jpeg")},
        )
        response = client.get("/api/v1/cloud/uploads")
        assert response.status_code == 200
        data = response.json()
        # Background task runs synchronously in TestClient
        assert data["count"] >= 1

    def test_status_filter_accepted(self, client):
        response = client.get("/api/v1/cloud/uploads?status=uploaded")
        assert response.status_code == 200


# ── MCP tool ─────────────────────────────────────────────────────────────────

class TestGetCloudSyncStatusTool:
    def test_empty(self, ctx):
        result = get_cloud_sync_status(ctx)
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["summary"] == {}

    def test_returns_after_upload(self, ctx, tmp_db, fake_image):
        worker = CloudUploadWorker(db=tmp_db, store=NoopStore())
        worker.queue_and_upload(fake_image, event_id="evt-cloud-001")
        result = get_cloud_sync_status(ctx)
        assert result["count"] == 1
        assert result["summary"].get("uploaded", 0) == 1

    def test_status_filter(self, ctx, tmp_db, fake_image):
        worker = CloudUploadWorker(db=tmp_db, store=NoopStore())
        worker.queue_and_upload(fake_image, event_id="evt-cloud-001")
        result = get_cloud_sync_status(ctx, status="pending")
        assert result["count"] == 0

    def test_via_dispatch(self, tmp_db):
        from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
        result = dispatch_tool("get_cloud_sync_status", {}, database_path=tmp_db.path)
        assert result["ok"] is True


# ── Config env-var parsing ────────────────────────────────────────────────────

class TestCloudConfig:
    def test_defaults_disabled(self):
        config = GatewayConfig()
        assert config.cloud_enabled is False
        assert config.cloud_provider == "noop"
        assert config.cloud_bucket == ""

    def test_from_env_parses_cloud_vars(self, monkeypatch):
        monkeypatch.setenv("CLAWCAM_CLOUD_ENABLED", "true")
        monkeypatch.setenv("CLAWCAM_CLOUD_PROVIDER", "s3")
        monkeypatch.setenv("CLAWCAM_CLOUD_BUCKET", "my-wildlife-bucket")
        monkeypatch.setenv("CLAWCAM_CLOUD_PREFIX", "cameras/")
        monkeypatch.setenv("CLAWCAM_CLOUD_REGION", "us-east-1")
        config = GatewayConfig.from_env()
        assert config.cloud_enabled is True
        assert config.cloud_provider == "s3"
        assert config.cloud_bucket == "my-wildlife-bucket"
        assert config.cloud_prefix == "cameras/"
        assert config.cloud_region == "us-east-1"


# ── Brain adapter policy ──────────────────────────────────────────────────────

class TestBrainAdapterCloudPolicy:
    def test_get_cloud_sync_status_auto_approved(self):
        from clawcam_adapter import ToolPolicy
        policy = ToolPolicy()
        assert policy.is_auto_approved("get_cloud_sync_status") is True
        assert policy.requires_approval("get_cloud_sync_status") is False
