"""Phase 13 (WS6): scoped approval tests for the brain adapter.

Covers the call/session/forever grant vocabulary (shared with Oh-Ben-Claw),
forever-grant persistence, audit, and funnel counters — against the real
stdio bridge subprocess.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_DIR = REPO_ROOT / "brain" / "oh-ben-claw-adapter"
GATEWAY_DIR = REPO_ROOT / "gateway"

sys.path.insert(0, str(ADAPTER_DIR))

from clawcam_adapter import (  # noqa: E402
    SCOPE_FOREVER,
    SCOPE_SESSION,
    ApprovalGrants,
    ApprovalRequired,
    ClawCamAdapter,
)


def _seed_gateway(tmp_path) -> Path:
    db_path = tmp_path / "gateway.db"
    bundle_dir = tmp_path / "bundle"
    SimulatedNode(device_id="node-ws6", name="Approvals Camera").write_bundle(
        bundle_dir,
        datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle_dir, db)
    return db_path


def _adapter(tmp_path, grants: ApprovalGrants | None = None) -> ClawCamAdapter:
    return ClawCamAdapter(
        gateway_dir=GATEWAY_DIR,
        db_path=_seed_gateway(tmp_path),
        grants=grants or ApprovalGrants(forever_path=tmp_path / "grants.json"),
    )


# ── Grants store ─────────────────────────────────────────────────────────────


def test_grants_session_scope_in_memory_only(tmp_path) -> None:
    path = tmp_path / "grants.json"
    g = ApprovalGrants(forever_path=path)
    g.grant("capture_now", SCOPE_SESSION)
    assert g.is_granted("capture_now")
    assert not path.exists(), "session grants must not persist"


def test_grants_forever_scope_persists(tmp_path) -> None:
    path = tmp_path / "grants.json"
    ApprovalGrants(forever_path=path).grant("capture_now", SCOPE_FOREVER)
    reloaded = ApprovalGrants(forever_path=path)
    assert reloaded.is_granted("capture_now")


def test_grants_revoke(tmp_path) -> None:
    path = tmp_path / "grants.json"
    g = ApprovalGrants(forever_path=path)
    g.grant("a", SCOPE_SESSION)
    g.grant("b", SCOPE_FOREVER)
    assert g.revoke("a") and g.revoke("b")
    assert not g.is_granted("a") and not g.is_granted("b")
    assert not g.revoke("missing")


def test_grants_unknown_scope_rejected(tmp_path) -> None:
    g = ApprovalGrants(forever_path=tmp_path / "g.json")
    with pytest.raises(ValueError):
        g.grant("x", "eternal")


# ── Adapter integration ───────────────────────────────────────────────────────


def test_gated_tool_denied_without_grant_and_audited(tmp_path) -> None:
    with _adapter(tmp_path) as adapter:
        with pytest.raises(ApprovalRequired):
            adapter.call_tool("capture_now", {"device_id": "node-ws6"})
        audit = adapter.approval_audit()
        assert audit[-1]["tool_name"] == "capture_now"
        assert audit[-1]["decision"] == "denied"
        assert adapter.funnel_summary()["capture_now"]["denied"] == 1


def test_session_scope_grant_covers_subsequent_calls(tmp_path) -> None:
    with _adapter(tmp_path) as adapter:
        adapter.call_tool(
            "capture_now", {"device_id": "node-ws6"}, approved=True, scope=SCOPE_SESSION
        )
        # Second call: no approved flag needed — session grant covers it.
        adapter.call_tool("capture_now", {"device_id": "node-ws6"})
        funnel = adapter.funnel_summary()["capture_now"]
        assert funnel["approved_session"] == 1
        assert funnel["granted_prior"] == 1
        assert funnel["denied"] == 0


def test_call_scope_does_not_persist_between_calls(tmp_path) -> None:
    with _adapter(tmp_path) as adapter:
        adapter.call_tool("capture_now", {"device_id": "node-ws6"}, approved=True)
        with pytest.raises(ApprovalRequired):
            adapter.call_tool("capture_now", {"device_id": "node-ws6"})


def test_forever_scope_survives_adapter_restart(tmp_path) -> None:
    grants_path = tmp_path / "grants.json"
    db = _seed_gateway(tmp_path)

    with ClawCamAdapter(
        gateway_dir=GATEWAY_DIR,
        db_path=db,
        grants=ApprovalGrants(forever_path=grants_path),
    ) as adapter:
        adapter.call_tool(
            "capture_now", {"device_id": "node-ws6"}, approved=True, scope=SCOPE_FOREVER
        )

    # New adapter instance, same grants file: no re-approval needed.
    with ClawCamAdapter(
        gateway_dir=GATEWAY_DIR,
        db_path=db,
        grants=ApprovalGrants(forever_path=grants_path),
    ) as adapter2:
        adapter2.call_tool("capture_now", {"device_id": "node-ws6"})
        assert adapter2.funnel_summary()["capture_now"]["granted_prior"] == 1


def test_unknown_scope_rejected_by_call_tool(tmp_path) -> None:
    with _adapter(tmp_path) as adapter:
        with pytest.raises(ValueError):
            adapter.call_tool("capture_now", {}, approved=True, scope="eternal")


def test_auto_approved_tools_bypass_funnel(tmp_path) -> None:
    with _adapter(tmp_path) as adapter:
        adapter.call_tool("get_recent_detections", {"limit": 3})
        # Read-only tools never enter the approval funnel.
        assert "get_recent_detections" not in adapter.funnel_summary()
