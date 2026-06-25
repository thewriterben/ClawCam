"""Phase 13 WS4 — approval-policy matrix eval (release gate).

Golden rule: every gated tool always asks; every auto-approved tool never
does. This eval enumerates the FULL tool catalogue from the live stdio
bridge, pins the exact partition, and behaviorally verifies the gate —
so a new tool that forgets a policy entry, or a policy drift, fails CI.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.mcp_server.stdio_server import APPROVAL_REQUIRED_TOOLS, TOOL_DEFINITIONS
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_DIR = REPO_ROOT / "brain" / "oh-ben-claw-adapter"
GATEWAY_DIR = REPO_ROOT / "gateway"

sys.path.insert(0, str(ADAPTER_DIR))

from clawcam_adapter import (  # noqa: E402
    ApprovalGrants,
    ApprovalRequired,
    ClawCamAdapter,
    ToolPolicy,
)


def _seed(tmp_path) -> Path:
    db_path = tmp_path / "gateway.db"
    bundle = tmp_path / "bundle"
    SimulatedNode(device_id="eval-node").write_bundle(
        bundle, datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    )
    import_directory(bundle, GatewayDatabase(db_path))
    return db_path


def test_eval_policy_partition_is_total_and_exact() -> None:
    """Every catalogued tool is in exactly one policy bucket — no orphans."""

    policy = ToolPolicy()
    catalogue = {t["name"] for t in TOOL_DEFINITIONS}

    orphans = catalogue - policy.auto_approve - policy.always_ask
    assert not orphans, f"tools with no policy entry: {sorted(orphans)}"

    overlap = policy.auto_approve & policy.always_ask
    assert not overlap, f"tools in both buckets: {sorted(overlap)}"

    stale = (policy.auto_approve | policy.always_ask) - catalogue
    assert not stale, f"policy entries for non-existent tools: {sorted(stale)}"

    # The gated bucket IS the approval SSOT, and auto-approve is the remainder.
    # Derived (not magic numbers) so adding a tool can't silently drift the gate.
    assert policy.always_ask == set(APPROVAL_REQUIRED_TOOLS)
    assert policy.auto_approve == catalogue - set(APPROVAL_REQUIRED_TOOLS)


def test_eval_every_gated_tool_asks(tmp_path) -> None:
    """Behavioral gate: all always_ask tools raise without approval."""

    policy = ToolPolicy()
    with ClawCamAdapter(
        gateway_dir=GATEWAY_DIR,
        db_path=_seed(tmp_path),
        grants=ApprovalGrants(forever_path=tmp_path / "g.json"),
    ) as adapter:
        for tool in sorted(policy.always_ask):
            with pytest.raises(ApprovalRequired):
                adapter.call_tool(tool, {})
        funnel = adapter.funnel_summary()
        assert all(funnel[t]["denied"] == 1 for t in policy.always_ask)


def test_eval_auto_approved_tools_never_ask(tmp_path) -> None:
    """Behavioral gate: representative read-only tools run with no approval."""

    with ClawCamAdapter(
        gateway_dir=GATEWAY_DIR,
        db_path=_seed(tmp_path),
        grants=ApprovalGrants(forever_path=tmp_path / "g.json"),
    ) as adapter:
        for tool, args in [
            ("get_recent_detections", {"limit": 1}),
            ("get_node_health", {"device_id": "eval-node"}),
            ("list_alert_rules", {}),
            ("list_profiles", {}),
            ("list_detectors", {}),
        ]:
            result = adapter.call_tool(tool, args)  # must not raise
            assert isinstance(result, dict)
        # None of these entered the approval funnel.
        assert adapter.funnel_summary() == {}
