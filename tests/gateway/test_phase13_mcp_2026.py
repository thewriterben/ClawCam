"""Phase 13 (WS2): MCP 2026-07-28 dual-mode tests.

Covers the bilingual stdio server (legacy initialize + 2026 server/discover,
handshake-less operation, _meta tolerance, tools/list cache metadata) and the
adapter's protocol-mode matrix against the real stdio bridge subprocess.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.mcp_server.stdio_server import (
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_2026,
    TOOLS_LIST_TTL_MS,
    ClawCamMCPServer,
)
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_DIR = REPO_ROOT / "brain" / "oh-ben-claw-adapter"
GATEWAY_DIR = REPO_ROOT / "gateway"

sys.path.insert(0, str(ADAPTER_DIR))

from clawcam_adapter import (  # noqa: E402
    PROTOCOL_MODE_2026,
    PROTOCOL_MODE_LEGACY,
    ClawCamAdapter,
)


def _seed_gateway(tmp_path) -> Path:
    db_path = tmp_path / "gateway.db"
    bundle_dir = tmp_path / "bundle"
    SimulatedNode(device_id="node-2026", name="Dual-Mode Camera").write_bundle(
        bundle_dir,
        datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle_dir, db)
    return db_path


def _req(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    request: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return request


# ── Server: bilingual lifecycle ──────────────────────────────────────────────


def test_server_discover_returns_2026_version(tmp_path) -> None:
    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))
    resp = server.handle_request(_req("server/discover", {}))
    assert resp is not None
    result = resp["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION_2026 == "2026-07-28"
    assert result["serverInfo"]["name"] == "clawcam-gateway"
    assert "tools" in result["capabilities"]


def test_server_initialize_still_answers_legacy(tmp_path) -> None:
    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))
    resp = server.handle_request(_req("initialize", {}))
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION == "2024-11-05"


def test_server_tools_list_carries_cache_metadata(tmp_path) -> None:
    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))
    resp = server.handle_request(_req("tools/list", {}))
    result = resp["result"]
    assert result["ttlMs"] == TOOLS_LIST_TTL_MS
    assert result["cacheScope"] == "private"
    assert len(result["tools"]) > 0


def test_server_handles_handshakeless_call_with_meta(tmp_path) -> None:
    """2026 clients send no initialize and carry _meta on every request."""

    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))
    params = {
        "name": "get_recent_detections",
        "arguments": {"limit": 5},
        "_meta": {
            "io.modelcontextprotocol/clientInfo": {"name": "test-2026", "version": "1.0"},
            "traceparent": "00-abc-def-01",
        },
    }
    resp = server.handle_request(_req("tools/call", params))
    assert resp is not None
    assert "error" not in resp
    assert resp["result"]["isError"] is False


def test_server_ping_works_without_handshake(tmp_path) -> None:
    server = ClawCamMCPServer(database_path=_seed_gateway(tmp_path))
    resp = server.handle_request(_req("ping", {}))
    assert resp["result"] == {}


# ── Adapter ↔ stdio bridge matrix ────────────────────────────────────────────


def _make_adapter(tmp_path, mode: str) -> ClawCamAdapter:
    return ClawCamAdapter(
        gateway_dir=GATEWAY_DIR,
        db_path=_seed_gateway(tmp_path),
        protocol_mode=mode,
    )


@pytest.mark.parametrize("mode", [PROTOCOL_MODE_LEGACY, PROTOCOL_MODE_2026])
def test_adapter_matrix_lists_and_calls_tools(tmp_path, mode) -> None:
    """Both client modes against the bilingual server: discover + call."""

    with _make_adapter(tmp_path, mode) as adapter:
        assert adapter.protocol_mode == mode
        tools = adapter.list_tools()
        names = {t["name"] for t in tools}
        assert "get_recent_detections" in names

        result = adapter.call_tool("get_recent_detections", {"limit": 3})
        assert result["ok"] is True
        assert result["detections"][0]["device_id"] == "node-2026"


@pytest.mark.parametrize("mode", [PROTOCOL_MODE_LEGACY, PROTOCOL_MODE_2026])
def test_adapter_matrix_approval_policy_enforced(tmp_path, mode) -> None:
    """Approval gating is protocol-mode independent."""

    from clawcam_adapter import ApprovalRequired

    with _make_adapter(tmp_path, mode) as adapter:
        with pytest.raises(ApprovalRequired):
            adapter.call_tool("capture_now", {"device_id": "node-2026"})


def test_adapter_2026_mode_skips_initialize(tmp_path) -> None:
    """In 2026 mode the adapter must not send the removed initialize method.

    The bilingual server would accept it, so we assert on the client's own
    behaviour: connect succeeds and the first wire message is not initialize.
    """

    adapter = _make_adapter(tmp_path, PROTOCOL_MODE_2026)
    sent: list[str] = []
    original_send = None

    adapter.connect()
    try:
        client = adapter._client
        assert client is not None
        original_send = client._send

        def recording_send(method, params=None):
            sent.append(method)
            return original_send(method, params)

        client._send = recording_send  # type: ignore[method-assign]
        adapter.call_tool("get_node_health", {"device_id": "node-2026"})
        assert "initialize" not in sent
    finally:
        adapter.close()


def test_adapter_rejects_unknown_mode(tmp_path) -> None:
    with pytest.raises(ValueError):
        ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path="x.db", protocol_mode="quantum-2030")


def test_client_meta_injection_preserves_existing_keys() -> None:
    """_meta merging must not clobber caller-set keys (e.g. traceparent)."""

    from clawcam_adapter import _MCPStdioClient

    captured: dict = {}

    class FakePipe:
        def write(self, line):
            import json as _json

            captured.update(_json.loads(line))

        def flush(self):
            pass

    class FakeStdout:
        def readline(self):
            import json as _json

            return _json.dumps({"jsonrpc": "2.0", "id": captured.get("id"), "result": {}}) + "\n"

    class FakeProc:
        stdin = FakePipe()
        stdout = FakeStdout()

    client = _MCPStdioClient(FakeProc(), protocol_mode=PROTOCOL_MODE_2026)
    client._send("tools/list", {"_meta": {"traceparent": "00-abc-def-01"}})

    meta = captured["params"]["_meta"]
    assert meta["traceparent"] == "00-abc-def-01"
    assert meta["io.modelcontextprotocol/clientInfo"]["name"] == "clawcam-brain-adapter"
