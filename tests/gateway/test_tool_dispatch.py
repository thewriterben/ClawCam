from __future__ import annotations

from datetime import datetime, timezone

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase


def test_dispatch_tool_for_recent_detections_and_health(tmp_path) -> None:
    db_path = tmp_path / "gateway.db"
    bundle_dir = tmp_path / "bundle"
    SimulatedNode(device_id="node-dispatch").write_bundle(
        bundle_dir,
        datetime(2026, 5, 12, 12, 30, tzinfo=timezone.utc),
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle_dir, db)

    recent = dispatch_tool("get_recent_detections", {"limit": 5}, database_path=db_path)
    assert recent["ok"] is True
    assert recent["detections"][0]["device_id"] == "node-dispatch"

    health = dispatch_tool("get_node_health", {"device_id": "node-dispatch"}, database_path=db_path)
    assert health["ok"] is True
    assert health["health"]["status"] == "ok"

    unknown = dispatch_tool("unknown_tool", {}, database_path=db_path)
    assert unknown["ok"] is False
    assert "unknown" in unknown["error"]
