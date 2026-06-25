"""Phase 15 (OBC) ⇄ Phase 13 (ClawCam): cross-repo MCP integration.

The single joint deliverable named in ``NEXT_PHASE_PLAN.md``: prove the full
brain path — ``brain ↔ clawcam_adapter ↔ stdio bridge ↔ gateway`` — works end to
end in **both** protocol modes (``legacy-2024`` and ``stateless-2026``), exercising
discovery, an auto-approved read, and a gated write authorized two ways (scope
grant and plan-mode). Then prove the MCP surface has **no session affinity** —
the stateless-2026 core requirement — across both the stdio bridge and the plain
HTTP tool surface. Passing this is the gate for flipping the default protocol
mode on 2026-07-28.

Boundaries are tested separately so a failure pinpoints which side broke.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_DIR = REPO_ROOT / "gateway"
BRAIN_DIR = REPO_ROOT / "brain" / "oh-ben-claw-adapter"

if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))
if str(BRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_DIR))

from clawcam_gateway.api.app import create_app  # noqa: E402
from clawcam_gateway.config import GatewayConfig  # noqa: E402
from clawcam_gateway.ingest.cli import import_directory  # noqa: E402
from clawcam_gateway.mcp_server.stdio_server import (  # noqa: E402
    ClawCamMCPServer,
    tool_catalog,
)
from clawcam_gateway.simulator.node_simulator import SimulatedNode  # noqa: E402
from clawcam_gateway.storage.database import GatewayDatabase  # noqa: E402

from clawcam_adapter import (  # noqa: E402
    PROTOCOL_MODE_2026,
    PROTOCOL_MODE_LEGACY,
    SCOPE_SESSION,
    ApprovalRequired,
    ArgumentBound,
    ClawCamAdapter,
    PlanStep,
    PlanViolationError,
)

from fastapi.testclient import TestClient  # noqa: E402

DEVICE = "node-x15"
BOTH_MODES = [PROTOCOL_MODE_LEGACY, PROTOCOL_MODE_2026]


def _seed(tmp_path) -> Path:
    db_path = tmp_path / "gateway.db"
    bundle = tmp_path / "bundle"
    SimulatedNode(device_id=DEVICE, name="Cross-Repo Camera").write_bundle(
        bundle, datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle, db)
    return db_path


def _adapter(tmp_path, mode: str) -> ClawCamAdapter:
    return ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=_seed(tmp_path), protocol_mode=mode)


# ── Full brain flow, both protocol modes ───────────────────────────────────


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_discovery_serves_full_catalog_in_both_modes(tmp_path, mode) -> None:
    with _adapter(tmp_path, mode) as adapter:
        assert adapter.protocol_mode == mode
        names = {t["name"] for t in adapter.list_tools()}
        # The brain sees the identical full catalog regardless of handshake.
        assert names == {t["name"] for t in tool_catalog()}
        assert len(names) >= 30


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_auto_approved_read_in_both_modes(tmp_path, mode) -> None:
    with _adapter(tmp_path, mode) as adapter:
        result = adapter.call_tool("get_recent_detections", {"limit": 5})
        assert result.get("ok") is True
        # Read tools never enter the approval funnel.
        assert "get_recent_detections" not in adapter.funnel_summary()


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_gated_write_via_scope_grant_in_both_modes(tmp_path, mode) -> None:
    with _adapter(tmp_path, mode) as adapter:
        # First call grants for the session; second is covered without a flag.
        adapter.call_tool(
            "capture_now", {"device_id": DEVICE}, approved=True, scope=SCOPE_SESSION
        )
        adapter.call_tool("capture_now", {"device_id": DEVICE})
        funnel = adapter.funnel_summary()["capture_now"]
        assert funnel["approved_session"] == 1
        assert funnel["granted_prior"] == 1
        assert funnel["denied"] == 0


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_gated_write_via_plan_mode_in_both_modes(tmp_path, mode) -> None:
    with _adapter(tmp_path, mode) as adapter:
        pid = adapter.approve_plan([
            PlanStep("capture_now", {"device_id": ArgumentBound.exact(DEVICE)})
        ])
        # The plan is the approval — no per-call flag, no prior grant. We assert
        # the authorization outcome (the call passed the gate and was dispatched
        # without raising), not capture_now's domain result, which depends on
        # device capabilities the gateway validates separately.
        result = adapter.call_tool("capture_now", {"device_id": DEVICE}, plan_id=pid)
        assert isinstance(result, dict)  # reached the gateway, no gate exception
        assert adapter.funnel_summary()["capture_now"]["approved_plan"] == 1
        assert adapter.active_plan_count() == 0  # single-step plan consumed


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_plan_violation_halts_in_both_modes(tmp_path, mode) -> None:
    with _adapter(tmp_path, mode) as adapter:
        pid = adapter.approve_plan([
            PlanStep("capture_now", {"device_id": ArgumentBound.exact(DEVICE)})
        ])
        with pytest.raises(PlanViolationError):
            adapter.call_tool("capture_now", {"device_id": "intruder"}, plan_id=pid)
        assert adapter.active_plan_count() == 0  # revoked on drift


@pytest.mark.parametrize("mode", BOTH_MODES)
def test_ungated_denial_in_both_modes(tmp_path, mode) -> None:
    with _adapter(tmp_path, mode) as adapter:
        with pytest.raises(ApprovalRequired):
            adapter.call_tool("capture_now", {"device_id": DEVICE})


# ── No session affinity: stdio bridge (stateless-2026 core) ────────────────


def test_stdio_call_works_without_any_handshake(tmp_path) -> None:
    """A 2026 client sends no initialize; a bare tools/call must still work."""
    server = ClawCamMCPServer(database_path=_seed(tmp_path))
    resp = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "get_recent_detections", "arguments": {"limit": 3}},
    })
    assert resp["id"] == 1
    assert resp["result"]["isError"] is False


def test_stdio_requests_are_order_independent(tmp_path) -> None:
    """No cross-request session state: call before list, list after call."""
    server = ClawCamMCPServer(database_path=_seed(tmp_path))
    call = server.handle_request({
        "jsonrpc": "2.0", "id": "a", "method": "tools/call",
        "params": {"name": "get_recent_detections", "arguments": {}},
    })
    listing = server.handle_request({"jsonrpc": "2.0", "id": "b", "method": "tools/list"})
    assert call["result"]["isError"] is False
    assert len(listing["result"]["tools"]) >= 30


def test_two_independent_stdio_servers_agree(tmp_path) -> None:
    """Independent server instances on the same DB are interchangeable —
    there is no per-connection session a client could be pinned to."""
    db = _seed(tmp_path)
    a = ClawCamMCPServer(database_path=db).handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    b = ClawCamMCPServer(database_path=db).handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    assert [t["name"] for t in a["result"]["tools"]] == [t["name"] for t in b["result"]["tools"]]


# ── No session affinity: plain HTTP tool surface ───────────────────────────


def _client(tmp_path) -> TestClient:
    app = create_app(
        GatewayConfig(database_path=_seed(tmp_path), media_dir=tmp_path / "media")
    )
    return TestClient(app)


def test_http_tool_call_works_as_first_request_no_session(tmp_path) -> None:
    c = _client(tmp_path)
    # A tool POST is the very first request — no login, no handshake, no cookie.
    resp = c.post("/api/v1/tools/get_recent_detections", json={"arguments": {"limit": 3}})
    assert resp.status_code == 200
    assert resp.json().get("ok") is True
    # The surface sets no session cookie.
    assert "set-cookie" not in {k.lower() for k in resp.headers}


def test_http_two_fresh_clients_are_interchangeable(tmp_path) -> None:
    """Two clients with no shared cookie jar both succeed identically —
    proving requests are not bound to a session established on another client."""
    c1, c2 = _client(tmp_path), _client(tmp_path)
    t1 = c1.get("/api/v1/tools").json()["tools"]
    t2 = c2.get("/api/v1/tools").json()["tools"]
    assert [t["name"] for t in t1] == [t["name"] for t in t2]
    # And the HTTP catalog matches what the MCP bridge advertises.
    assert {t["name"] for t in t1} == {t["name"] for t in tool_catalog()}
