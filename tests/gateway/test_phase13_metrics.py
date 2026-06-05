"""Phase 13 (WS5): tool-call audit + gateway metrics tests."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase


def _seed(tmp_path):
    db_path = tmp_path / "gateway.db"
    bundle = tmp_path / "bundle"
    SimulatedNode(device_id="obs-node").write_bundle(
        bundle, datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle, db)
    return db_path, db


def test_dispatch_records_audit_rows(tmp_path) -> None:
    db_path, db = _seed(tmp_path)

    ok = dispatch_tool("get_recent_detections", {"limit": 2}, database_path=db_path, source="mcp-stdio")
    assert ok["ok"] is True
    bad = dispatch_tool("unknown_tool", {}, database_path=db_path, source="rest")
    assert bad["ok"] is False

    audit = db.list_tool_call_audit()
    assert len(audit) == 2
    # Newest first.
    assert audit[0]["tool_name"] == "unknown_tool"
    assert audit[0]["ok"] == 0
    assert audit[0]["source"] == "rest"
    assert audit[1]["tool_name"] == "get_recent_detections"
    assert audit[1]["ok"] == 1
    assert audit[1]["source"] == "mcp-stdio"
    assert len(audit[1]["args_sha256"]) == 64
    assert audit[1]["duration_ms"] >= 0


def test_identical_args_hash_identically(tmp_path) -> None:
    db_path, db = _seed(tmp_path)
    dispatch_tool("get_recent_detections", {"limit": 2}, database_path=db_path)
    dispatch_tool("get_recent_detections", {"limit": 2}, database_path=db_path)
    dispatch_tool("get_recent_detections", {"limit": 3}, database_path=db_path)
    audit = db.list_tool_call_audit()
    hashes = [row["args_sha256"] for row in reversed(audit)]
    assert hashes[0] == hashes[1]
    assert hashes[0] != hashes[2]


def test_tool_call_stats_aggregates(tmp_path) -> None:
    db_path, db = _seed(tmp_path)
    for _ in range(3):
        dispatch_tool("get_recent_detections", {"limit": 1}, database_path=db_path)
    dispatch_tool("unknown_tool", {}, database_path=db_path)

    stats = {s["tool_name"]: s for s in db.tool_call_stats()}
    assert stats["get_recent_detections"]["calls"] == 3
    assert stats["get_recent_detections"]["errors"] == 0
    assert stats["unknown_tool"]["calls"] == 1
    assert stats["unknown_tool"]["errors"] == 1


def test_metrics_endpoint_shape(tmp_path) -> None:
    db_path, _ = _seed(tmp_path)
    dispatch_tool("get_recent_detections", {"limit": 1}, database_path=db_path)

    config = GatewayConfig(database_path=db_path, media_dir=tmp_path / "media")
    client = TestClient(create_app(config))

    r = client.get("/api/v1/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["counts"]["devices"] == 1
    assert body["counts"]["events"] >= 1
    assert body["tool_calls"]["total"] >= 1
    assert any(t["tool_name"] == "get_recent_detections" for t in body["tool_calls"]["by_tool"])

    # REST tool calls are themselves audited with source="rest".
    client.post("/api/v1/tools/get_node_health", json={"arguments": {"device_id": "obs-node"}})
    audit = client.get("/api/v1/tool-audit").json()["audit"]
    assert audit[0]["tool_name"] == "get_node_health"
    assert audit[0]["source"] == "rest"
