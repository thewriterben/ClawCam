"""Phase 5 tests: CSV data export, cloud retry, dashboard enrichment, MCP tool.

Coverage
--------
- export.py: events_to_csv, detections_to_csv, export_events_csv,
  export_detections_csv, csv_filename
- REST: GET /api/v1/export/events.csv, GET /api/v1/export/detections.csv,
  POST /api/v1/cloud/retry
- Dashboard payload: inference + cloud fields present, auto-refresh meta tag
- MCP tool: export_detections_csv tool function, dispatch, stdio definition
- Brain adapter: export_detections_csv is auto-approved
"""

from __future__ import annotations

import csv
import io
import sys
import tempfile
from pathlib import Path

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

from clawcam_gateway.api.app import create_app
from clawcam_gateway.api.dashboard import render_dashboard, _detection_row
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.ingest.export import (
    DETECTIONS_COLUMNS,
    EVENTS_COLUMNS,
    csv_filename,
    detections_to_csv,
    events_to_csv,
    export_detections_csv,
    export_events_csv,
)
from clawcam_gateway.mcp_server.stdio_server import TOOL_DEFINITIONS
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import ToolContext, export_detections_csv as tool_export_detections_csv
from clawcam_adapter import ToolPolicy  # type: ignore[import]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "test.db")
    # Register a device
    db.upsert_device({
        "device_id": "export-dev-1",
        "name": "Export Test Node",
        "hardware": "test",
        "firmware_version": "1.0.0",
        "capabilities": ["cap_clawcam_camera_trap"],
    })
    return db


@pytest.fixture()
def db_with_events(tmp_db: GatewayDatabase) -> GatewayDatabase:
    """DB pre-populated with two events."""
    tmp_db.add_event({
        "event_id": "evt-export-001",
        "event_type": "motion_detected",
        "device_id": "export-dev-1",
        "timestamp": "2026-05-14T10:00:00Z",
        "time_source": "gps",
        "source": "pir",
        "media": [{"media_id": "m1"}, {"media_id": "m2"}],
        "metadata": {"trigger": "pir"},
    })
    tmp_db.add_event({
        "event_id": "evt-export-002",
        "event_type": "timelapse",
        "device_id": "export-dev-1",
        "timestamp": "2026-05-14T11:00:00Z",
        "time_source": "rtc",
        "source": "timer",
        "media": [],
        "metadata": {},
    })
    return tmp_db


@pytest.fixture()
def db_with_inference(db_with_events: GatewayDatabase) -> GatewayDatabase:
    result = InferenceResult(
        model_name="mock_detector",
        model_version="1.0.0",
        detections=[Detection("animal", 0.91, [0, 0, 1, 1], "Odocoileus virginianus")],
    )
    db_with_events.save_inference_result("evt-export-001", "/media/evt-export-001.jpg", result)
    return db_with_events


@pytest.fixture()
def client(tmp_path: Path, db_with_inference: GatewayDatabase) -> TestClient:
    cfg = GatewayConfig(
        database_path=db_with_inference.path,
        media_dir=tmp_path / "media",
    )
    app = create_app(config=cfg)
    return TestClient(app)


# ── export.py unit tests ──────────────────────────────────────────────────────

class TestEventsToCSV:
    def test_header_row(self):
        csv_text = events_to_csv([])
        lines = csv_text.strip().splitlines()
        assert lines[0] == ",".join(EVENTS_COLUMNS)

    def test_one_event_row(self):
        events = [{
            "event_id": "evt-1",
            "event_type": "motion_detected",
            "device_id": "dev-1",
            "timestamp": "2026-05-14T10:00:00Z",
            "time_source": "gps",
            "source": "pir",
            "media": [{"media_id": "m1"}],
            "metadata": {"trigger": "pir"},
        }]
        csv_text = events_to_csv(events)
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        assert len(rows) == 1
        row = rows[0]
        assert row["event_id"] == "evt-1"
        assert row["event_type"] == "motion_detected"
        assert row["media_count"] == "1"
        assert row["trigger"] == "pir"

    def test_media_count_aggregation(self):
        events = [{"event_id": "e", "media": [{"media_id": "a"}, {"media_id": "b"}], "metadata": {}}]
        csv_text = events_to_csv(events)
        reader = csv.DictReader(io.StringIO(csv_text))
        assert next(reader)["media_count"] == "2"

    def test_empty_events_returns_header_only(self):
        csv_text = events_to_csv([])
        lines = [l for l in csv_text.splitlines() if l]
        assert len(lines) == 1

    def test_missing_fields_use_empty_string(self):
        csv_text = events_to_csv([{}])
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        for col in EVENTS_COLUMNS:
            assert col in row


class TestDetectionsToCSV:
    def test_header_row(self):
        csv_text = detections_to_csv([])
        assert csv_text.splitlines()[0] == ",".join(DETECTIONS_COLUMNS)

    def test_one_detection_row(self):
        results = [{
            "event_id": "evt-1",
            "ran_at": "2026-05-14T10:01:00Z",
            "model_name": "mock_detector",
            "model_version": "1.0.0",
            "top_label": "animal",
            "top_confidence": 0.91,
            "top_species": "Odocoileus virginianus",
            "media_path": "/media/evt-1.jpg",
            "detections": [{"label": "animal"}],
        }]
        csv_text = detections_to_csv(results)
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        assert row["event_id"] == "evt-1"
        assert row["top_label"] == "animal"
        assert row["detection_count"] == "1"
        assert "virginianus" in row["top_species"]

    def test_empty_results_returns_header_only(self):
        lines = [l for l in detections_to_csv([]).splitlines() if l]
        assert len(lines) == 1


class TestDBWrappers:
    def test_export_events_csv_returns_rows(self, db_with_events: GatewayDatabase):
        csv_text = export_events_csv(db_with_events, limit=10)
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        assert len(rows) == 2
        ids = {r["event_id"] for r in rows}
        assert "evt-export-001" in ids
        assert "evt-export-002" in ids

    def test_export_events_csv_device_filter(self, db_with_events: GatewayDatabase):
        csv_text = export_events_csv(db_with_events, device_id="export-dev-1")
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        assert all(r["device_id"] == "export-dev-1" for r in rows)

    def test_export_events_csv_unknown_device_empty(self, db_with_events: GatewayDatabase):
        csv_text = export_events_csv(db_with_events, device_id="nonexistent-999")
        lines = [l for l in csv_text.splitlines() if l]
        assert len(lines) == 1  # header only

    def test_export_detections_csv_returns_rows(self, db_with_inference: GatewayDatabase):
        csv_text = export_detections_csv(db_with_inference, limit=10)
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["top_label"] == "animal"

    def test_export_detections_csv_label_filter(self, db_with_inference: GatewayDatabase):
        csv_text = export_detections_csv(db_with_inference, label="animal")
        reader = csv.DictReader(io.StringIO(csv_text))
        assert len(list(reader)) == 1

    def test_export_detections_csv_label_no_match(self, db_with_inference: GatewayDatabase):
        csv_text = export_detections_csv(db_with_inference, label="person")
        lines = [l for l in csv_text.splitlines() if l]
        assert len(lines) == 1  # header only

    def test_export_detections_csv_min_confidence_filter(self, db_with_inference: GatewayDatabase):
        csv_text = export_detections_csv(db_with_inference, min_confidence=0.99)
        lines = [l for l in csv_text.splitlines() if l]
        assert len(lines) == 1  # header only — 0.91 < 0.99

    def test_csv_filename_format(self):
        name = csv_filename("events")
        assert name.startswith("events_")
        assert name.endswith(".csv")
        assert "T" in name  # ISO timestamp


# ── REST export endpoints ─────────────────────────────────────────────────────

class TestCSVExportEndpoints:
    def test_events_csv_200(self, client: TestClient):
        resp = client.get("/api/v1/export/events.csv")
        assert resp.status_code == 200

    def test_events_csv_content_type(self, client: TestClient):
        resp = client.get("/api/v1/export/events.csv")
        assert "text/csv" in resp.headers["content-type"]

    def test_events_csv_content_disposition(self, client: TestClient):
        resp = client.get("/api/v1/export/events.csv")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "events_" in resp.headers["content-disposition"]

    def test_events_csv_has_header(self, client: TestClient):
        resp = client.get("/api/v1/export/events.csv")
        first_line = resp.text.splitlines()[0]
        assert first_line == ",".join(EVENTS_COLUMNS)

    def test_events_csv_has_data_rows(self, client: TestClient):
        resp = client.get("/api/v1/export/events.csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) >= 1

    def test_events_csv_device_id_filter(self, client: TestClient):
        resp = client.get("/api/v1/export/events.csv?device_id=export-dev-1")
        assert resp.status_code == 200
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            assert row["device_id"] == "export-dev-1"

    def test_detections_csv_200(self, client: TestClient):
        resp = client.get("/api/v1/export/detections.csv")
        assert resp.status_code == 200

    def test_detections_csv_content_type(self, client: TestClient):
        resp = client.get("/api/v1/export/detections.csv")
        assert "text/csv" in resp.headers["content-type"]

    def test_detections_csv_content_disposition(self, client: TestClient):
        resp = client.get("/api/v1/export/detections.csv")
        assert "detections_" in resp.headers["content-disposition"]

    def test_detections_csv_has_header(self, client: TestClient):
        resp = client.get("/api/v1/export/detections.csv")
        assert resp.text.splitlines()[0] == ",".join(DETECTIONS_COLUMNS)

    def test_detections_csv_has_data_rows(self, client: TestClient):
        resp = client.get("/api/v1/export/detections.csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        assert len(list(reader)) == 1

    def test_detections_csv_label_filter(self, client: TestClient):
        resp = client.get("/api/v1/export/detections.csv?label=person")
        assert resp.status_code == 200
        lines = [l for l in resp.text.splitlines() if l]
        assert len(lines) == 1  # header only — no person detections

    def test_detections_csv_min_confidence_filter(self, client: TestClient):
        resp = client.get("/api/v1/export/detections.csv?min_confidence=0.5")
        assert resp.status_code == 200
        reader = csv.DictReader(io.StringIO(resp.text))
        assert len(list(reader)) == 1  # 0.91 >= 0.5


# ── Cloud retry endpoint ──────────────────────────────────────────────────────

class TestCloudRetryEndpoint:
    def test_retry_returns_ok(self, client: TestClient):
        resp = client.post("/api/v1/cloud/retry")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "retried" in body

    def test_retry_no_failed_uploads_retried_zero(self, client: TestClient):
        # No failed uploads exist in this fixture — retried should be 0
        resp = client.post("/api/v1/cloud/retry")
        assert resp.json()["retried"] == 0

    def test_retry_with_failed_upload(self, tmp_path: Path, db_with_inference: GatewayDatabase):
        """Seed a failed upload and verify retry count increments."""
        # Add a failed cloud upload record
        upload_id = db_with_inference.add_cloud_upload(
            event_id="evt-export-001",
            media_path="/media/evt-export-001.jpg",
            provider="noop",
        )
        db_with_inference.update_cloud_upload(upload_id, status="failed", error="connection error")

        cfg = GatewayConfig(
            database_path=db_with_inference.path,
            media_dir=tmp_path / "media",
        )
        app = create_app(config=cfg)
        c = TestClient(app)
        resp = c.post("/api/v1/cloud/retry")
        assert resp.status_code == 200
        assert resp.json()["retried"] == 1


# ── Dashboard enrichment ──────────────────────────────────────────────────────

class TestDashboardPayload:
    def test_dashboard_data_has_detection_fields(self, client: TestClient):
        resp = client.get("/api/v1/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert "recent_detections" in body
        assert "detection_label_counts" in body
        assert "detection_species_counts" in body

    def test_dashboard_data_has_cloud_fields(self, client: TestClient):
        resp = client.get("/api/v1/dashboard")
        body = resp.json()
        assert "cloud_summary" in body
        assert "cloud_enabled" in body

    def test_dashboard_detection_counts_correct(self, client: TestClient):
        resp = client.get("/api/v1/dashboard")
        body = resp.json()
        assert body["detection_label_counts"].get("animal", 0) >= 1

    def test_dashboard_html_has_auto_refresh(self, client: TestClient):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert 'http-equiv="refresh"' in resp.text
        assert 'content="30"' in resp.text

    def test_dashboard_html_has_inference_section(self, client: TestClient):
        resp = client.get("/dashboard")
        assert "AI Inference" in resp.text

    def test_dashboard_html_has_cloud_section(self, client: TestClient):
        resp = client.get("/dashboard")
        assert "Cloud Sync" in resp.text

    def test_dashboard_html_has_export_links(self, client: TestClient):
        resp = client.get("/dashboard")
        assert "events.csv" in resp.text
        assert "detections.csv" in resp.text

    def test_detection_row_renders_confidence(self):
        result = {
            "event_id": "evt-1",
            "model_name": "mock",
            "top_label": "animal",
            "top_confidence": 0.91,
            "top_species": "deer",
            "ran_at": "2026-05-14T10:01:00Z",
        }
        html = _detection_row(result)
        assert "0.91" in html
        assert "animal" in html
        assert "deer" in html

    def test_render_dashboard_includes_species_table(self):
        data = {
            "gateway_id": "gw-test",
            "timestamp": "2026-05-14T12:00:00Z",
            "device_count": 0,
            "event_count": 0,
            "devices": [],
            "recent_events": [],
            "health_by_device": {},
            "event_counts": {},
            "label_counts": {},
            "recent_detections": [],
            "detection_label_counts": {"animal": 3},
            "detection_species_counts": {"Cervus elaphus": 2, "Sus scrofa": 1},
            "cloud_summary": {"pending": 0, "uploaded": 0, "failed": 0},
            "cloud_enabled": False,
        }
        html = render_dashboard(data)
        assert "Top Species" in html
        assert "Cervus elaphus" in html
        assert "DISABLED" in html


# ── MCP tool: export_detections_csv ──────────────────────────────────────────

class TestExportDetectionsCSVTool:
    def test_tool_returns_ok(self, db_with_inference: GatewayDatabase):
        ctx = ToolContext(database_path=db_with_inference.path)
        result = tool_export_detections_csv(ctx)
        assert result["ok"] is True

    def test_tool_returns_csv_string(self, db_with_inference: GatewayDatabase):
        ctx = ToolContext(database_path=db_with_inference.path)
        result = tool_export_detections_csv(ctx)
        assert isinstance(result["csv"], str)
        assert "event_id" in result["csv"]

    def test_tool_row_count_matches(self, db_with_inference: GatewayDatabase):
        ctx = ToolContext(database_path=db_with_inference.path)
        result = tool_export_detections_csv(ctx)
        assert result["row_count"] == 1

    def test_tool_filters_passed_through(self, db_with_inference: GatewayDatabase):
        ctx = ToolContext(database_path=db_with_inference.path)
        result = tool_export_detections_csv(ctx, label="person")
        assert result["ok"] is True
        assert result["row_count"] == 0  # no person detections
        assert result["filters"]["label"] == "person"

    def test_tool_limit_clamped(self, db_with_inference: GatewayDatabase):
        ctx = ToolContext(database_path=db_with_inference.path)
        result = tool_export_detections_csv(ctx, limit=99999)
        assert result["filters"]["limit"] == 10000

    def test_tool_empty_db_returns_header_only(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_export_detections_csv(ctx)
        assert result["ok"] is True
        assert result["row_count"] == 0
        assert result["csv"].strip().startswith("event_id")


# ── Dispatch integration ──────────────────────────────────────────────────────

class TestDispatchExportTool:
    def test_dispatch_export_detections_csv(self, db_with_inference: GatewayDatabase):
        result = dispatch_tool(
            "export_detections_csv",
            {},
            database_path=db_with_inference.path,
        )
        assert result["ok"] is True
        assert "csv" in result

    def test_dispatch_export_with_args(self, db_with_inference: GatewayDatabase):
        result = dispatch_tool(
            "export_detections_csv",
            {"limit": 50, "label": "animal"},
            database_path=db_with_inference.path,
        )
        assert result["ok"] is True
        assert result["filters"]["label"] == "animal"

    def test_dispatch_unknown_tool_returns_error(self, tmp_db: GatewayDatabase):
        result = dispatch_tool("nonexistent_tool", {}, database_path=tmp_db.path)
        assert result["ok"] is False


# ── Stdio server definition ───────────────────────────────────────────────────

class TestStdioServerDefinition:
    def test_export_detections_csv_in_tool_list(self):
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "export_detections_csv" in names

    def test_export_detections_csv_schema(self):
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "export_detections_csv")
        schema = defn["inputSchema"]
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "limit" in props
        assert "label" in props
        assert "min_confidence" in props
        assert "species" in props

    def test_export_detections_csv_no_required_args(self):
        defn = next(t for t in TOOL_DEFINITIONS if t["name"] == "export_detections_csv")
        assert "required" not in defn["inputSchema"]


# ── Brain adapter policy ──────────────────────────────────────────────────────

class TestBrainAdapterPolicy:
    def test_export_detections_csv_is_auto_approved(self):
        policy = ToolPolicy()
        assert policy.is_auto_approved("export_detections_csv")
        assert not policy.requires_approval("export_detections_csv")

    def test_approval_gated_tools_unchanged(self):
        policy = ToolPolicy()
        for tool in ("capture_now", "apply_config_patch", "queue_firmware_update"):
            assert policy.requires_approval(tool)
            assert not policy.is_auto_approved(tool)

    def test_all_read_tools_are_auto_approved(self):
        policy = ToolPolicy()
        read_tools = [
            "get_recent_detections",
            "get_node_health",
            "generate_daily_summary",
            "list_pending_commands",
            "list_capabilities",
            "get_inference_results",
            "list_species_detections",
            "list_firmware_builds",
            "get_cloud_sync_status",
            "export_detections_csv",
        ]
        for tool in read_tools:
            assert policy.is_auto_approved(tool), f"{tool} should be auto-approved"
