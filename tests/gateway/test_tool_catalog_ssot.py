"""S0 drift guard: the ClawCam tool catalog has a single source of truth.

The MCP server's ``TOOL_DEFINITIONS`` + ``APPROVAL_REQUIRED_TOOLS`` is canonical.
This test asserts the HTTP ``GET /api/v1/tools`` endpoint and the brain adapter's
approval policy stay consistent with it, so the three can never drift apart again
(they previously listed 5 / 16 / 32 tools respectively).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.mcp_server.stdio_server import (
    APPROVAL_REQUIRED_TOOLS,
    TOOL_DEFINITIONS,
    tool_catalog,
)


def _client(tmp_path) -> TestClient:
    app = create_app(
        GatewayConfig(database_path=tmp_path / "db.sqlite", media_dir=tmp_path / "media")
    )
    return TestClient(app)


def test_http_endpoint_matches_catalog(tmp_path):
    resp = _client(tmp_path).get("/api/v1/tools")
    assert resp.status_code == 200
    http = {t["name"]: t["approval_required"] for t in resp.json()["tools"]}
    catalog = {t["name"]: t["approval_required"] for t in tool_catalog()}
    assert http == catalog
    # the endpoint serves the FULL MCP catalog, not a hand-written subset
    assert set(http) == {t["name"] for t in TOOL_DEFINITIONS}
    assert len(http) == len(TOOL_DEFINITIONS) >= 30


def test_approval_flags_derive_from_single_set(tmp_path):
    http = {
        t["name"]: t["approval_required"]
        for t in _client(tmp_path).get("/api/v1/tools").json()["tools"]
    }
    flagged = {name for name, required in http.items() if required}
    assert flagged == set(APPROVAL_REQUIRED_TOOLS)


def test_every_catalog_tool_is_unique():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names)), "duplicate tool names in TOOL_DEFINITIONS"
    # approval set must be a subset of the catalog (no phantom approval entries)
    assert set(APPROVAL_REQUIRED_TOOLS) <= set(names)


def test_brain_adapter_policy_matches_catalog():
    # The brain adapter (on sys.path) must classify exactly the catalog tools and
    # its write set must equal the gateway approval set. Skips if the adapter
    # package isn't importable in this environment.
    clawcam_adapter = pytest.importorskip("clawcam_adapter")
    policy = clawcam_adapter.ToolPolicy()
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert (set(policy.auto_approve) | set(policy.always_ask)) == names
    assert set(policy.auto_approve).isdisjoint(set(policy.always_ask))
    assert set(policy.always_ask) == set(APPROVAL_REQUIRED_TOOLS)
