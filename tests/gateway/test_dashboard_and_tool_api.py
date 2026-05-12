from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase


def test_tool_api_and_dashboard_endpoints(tmp_path) -> None:
    db_path = tmp_path / "gateway.db"
    bundle_dir = tmp_path / "bundle"
    SimulatedNode(device_id="node-api", name="API Test Camera").write_bundle(
        bundle_dir,
        datetime(2026, 5, 12, 13, 0, tzinfo=timezone.utc),
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle_dir, db)

    app = create_app(GatewayConfig(database_path=db_path, media_dir=tmp_path / "media"))
    client = TestClient(app)

    tools_response = client.get("/api/v1/tools")
    assert tools_response.status_code == 200
    tool_names = {tool["name"] for tool in tools_response.json()["tools"]}
    assert "get_recent_detections" in tool_names
    assert "get_node_health" in tool_names

    recent_response = client.post(
        "/api/v1/tools/get_recent_detections",
        json={"arguments": {"limit": 5}},
    )
    assert recent_response.status_code == 200
    assert recent_response.json()["ok"] is True
    assert recent_response.json()["detections"][0]["device_id"] == "node-api"

    health_response = client.post(
        "/api/v1/tools/get_node_health",
        json={"arguments": {"device_id": "node-api"}},
    )
    assert health_response.status_code == 200
    assert health_response.json()["ok"] is True
    assert health_response.json()["health"]["status"] == "ok"

    dashboard_json = client.get("/api/v1/dashboard")
    assert dashboard_json.status_code == 200
    assert dashboard_json.json()["device_count"] == 1
    assert dashboard_json.json()["event_count"] == 1
    assert dashboard_json.json()["label_counts"]["animal"] == 1

    dashboard_html = client.get("/dashboard")
    assert dashboard_html.status_code == 200
    assert "text/html" in dashboard_html.headers["content-type"]
    assert "ClawCam Gateway Dashboard" in dashboard_html.text
    assert "node-api" in dashboard_html.text


def test_unknown_tool_returns_404(tmp_path) -> None:
    app = create_app(GatewayConfig(database_path=tmp_path / "gateway.db", media_dir=tmp_path / "media"))
    client = TestClient(app)

    response = client.post("/api/v1/tools/unknown_tool", json={"arguments": {}})
    assert response.status_code == 404
