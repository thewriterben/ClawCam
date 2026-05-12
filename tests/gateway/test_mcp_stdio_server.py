from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.mcp_server.stdio_server import ClawCamMCPServer, serve_stdio
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase


def _seed_gateway(tmp_path):
    db_path = tmp_path / "gateway.db"
    bundle_dir = tmp_path / "bundle"
    SimulatedNode(device_id="node-mcp", name="MCP Test Camera").write_bundle(
        bundle_dir,
        datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc),
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle_dir, db)
    return db_path


def test_mcp_initialize_and_tools_list(tmp_path) -> None:
    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))

    initialized = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialized is not None
    assert initialized["result"]["serverInfo"]["name"] == "clawcam-gateway"
    assert "tools" in initialized["result"]["capabilities"]

    listed = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert listed is not None
    tool_names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "get_recent_detections" in tool_names
    assert "get_node_health" in tool_names
    assert "generate_daily_summary" in tool_names


def test_mcp_tools_call_returns_gateway_data(tmp_path) -> None:
    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))

    response = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_node_health", "arguments": {"device_id": "node-mcp"}},
        }
    )
    assert response is not None
    assert response["result"]["isError"] is False
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["health"]["status"] == "ok"

    summary = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "generate_daily_summary", "arguments": {"report_date": "2026-05-12"}},
        }
    )
    assert summary is not None
    summary_payload = json.loads(summary["result"]["content"][0]["text"])
    assert summary_payload["event_count"] == 1
    assert summary_payload["label_counts"]["animal"] == 1


def test_mcp_stdio_loop_accepts_newline_delimited_json(tmp_path) -> None:
    db_path = _seed_gateway(tmp_path)
    stdin = StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
    )
    stdout = StringIO()

    serve_stdio(database_path=db_path, stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["id"] == 1
    assert responses[1]["id"] == 2
    assert any(tool["name"] == "get_recent_detections" for tool in responses[1]["result"]["tools"])


def test_mcp_unknown_method_returns_jsonrpc_error(tmp_path) -> None:
    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))
    response = server.handle_request({"jsonrpc": "2.0", "id": 99, "method": "unknown", "params": {}})
    assert response is not None
    assert response["error"]["code"] == -32601
