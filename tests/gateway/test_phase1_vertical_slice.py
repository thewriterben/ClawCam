from __future__ import annotations

from datetime import datetime, timezone

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import ToolContext, generate_daily_summary, get_node_health, get_recent_detections


def test_node_simulator_generates_importable_bundle(tmp_path) -> None:
    node = SimulatedNode(device_id="node-sim", deployment_id="deploy-sim", name="Sim Camera")
    paths = node.write_bundle(tmp_path / "bundle", datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc))

    assert set(paths) == {"device", "event", "health"}
    assert paths["device"].exists()
    assert paths["event"].exists()
    assert paths["health"].exists()


def test_import_directory_and_tools_complete_phase1_flow(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    db_path = tmp_path / "gateway.db"
    node = SimulatedNode(device_id="node-sim", deployment_id="deploy-sim", name="Sim Camera")
    node.write_bundle(bundle_dir, datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc))

    db = GatewayDatabase(db_path)
    imported = import_directory(bundle_dir, db)
    assert any(item.startswith("device:node-sim") for item in imported)
    assert any(item.startswith("event:") for item in imported)
    assert any(item.startswith("health:node-sim") for item in imported)

    context = ToolContext(database_path=db_path)
    recent = get_recent_detections(context, limit=10)
    assert recent["ok"] is True
    assert len(recent["detections"]) == 1
    assert recent["detections"][0]["device_id"] == "node-sim"

    health = get_node_health(context, "node-sim")
    assert health["ok"] is True
    assert health["health"]["battery"]["percentage"] == 72

    summary = generate_daily_summary(context, report_date="2026-05-12")
    assert summary["ok"] is True
    assert summary["event_count"] == 1
    assert summary["label_counts"]["animal"] == 1
