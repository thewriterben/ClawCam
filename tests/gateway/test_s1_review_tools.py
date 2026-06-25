"""S1: review tools exposed over the MCP/dispatch surface.

`list_observations_for_review` (read) and `set_review_state` (gated write) make
the review_state model usable by the brain. These tests drive the real
``dispatch_tool`` chokepoint and assert the catalog/approval wiring stays
consistent with the SSOT.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.mcp_server.stdio_server import (
    APPROVAL_REQUIRED_TOOLS,
    tool_catalog,
)
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.storage.database import GatewayDatabase


def _seed_result(db_path) -> int:
    db = GatewayDatabase(db_path)
    db.save_inference_result(
        "evt-r1", "/media/evt-r1.jpg",
        InferenceResult("megadetector", "5a", [Detection("deer", 0.9, [0, 0, 1, 1], "deer")]),
    )
    return db.get_inference_result("evt-r1")["result_id"]


# ── Catalog / approval wiring ───────────────────────────────────────────────


def test_new_tools_are_in_catalog_with_correct_approval() -> None:
    cat = {t["name"]: t["approval_required"] for t in tool_catalog()}
    assert cat.get("list_observations_for_review") is False  # read
    assert cat.get("set_review_state") is True               # gated write
    assert "set_review_state" in APPROVAL_REQUIRED_TOOLS
    assert "list_observations_for_review" not in APPROVAL_REQUIRED_TOOLS


# ── Dispatch behavior ───────────────────────────────────────────────────────


def test_set_review_state_via_dispatch_updates(tmp_path) -> None:
    db_path = tmp_path / "g.db"
    rid = _seed_result(db_path)
    out = dispatch_tool(
        "set_review_state",
        {"result_id": rid, "review_state": "verified", "reviewer": "ranger.kim", "note": "clear"},
        database_path=db_path,
        source="test",
    )
    assert out["ok"] is True
    assert out["result"]["review_state"] == "verified"
    assert out["result"]["reviewer"] == "ranger.kim"
    # Original detection preserved.
    assert out["result"]["top_label"] == "deer"


def test_list_observations_for_review_via_dispatch_filters(tmp_path) -> None:
    db_path = tmp_path / "g.db"
    rid = _seed_result(db_path)
    dispatch_tool(
        "set_review_state",
        {"result_id": rid, "review_state": "needs_review"},
        database_path=db_path, source="test",
    )
    out = dispatch_tool(
        "list_observations_for_review",
        {"review_state": "needs_review"},
        database_path=db_path, source="test",
    )
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["results"][0]["event_id"] == "evt-r1"
    # An empty state returns nothing, not an error.
    empty = dispatch_tool(
        "list_observations_for_review", {"review_state": "rejected"},
        database_path=db_path, source="test",
    )
    assert empty["ok"] is True and empty["count"] == 0


def test_set_review_state_invalid_state_is_soft_error(tmp_path) -> None:
    db_path = tmp_path / "g.db"
    rid = _seed_result(db_path)
    out = dispatch_tool(
        "set_review_state", {"result_id": rid, "review_state": "bear?!"},
        database_path=db_path, source="test",
    )
    assert out["ok"] is False and "valid" in out


def test_set_review_state_unknown_result_is_soft_error(tmp_path) -> None:
    out = dispatch_tool(
        "set_review_state", {"result_id": 999999, "review_state": "verified"},
        database_path=tmp_path / "g.db", source="test",
    )
    assert out["ok"] is False


# ── HTTP surface ────────────────────────────────────────────────────────────


def test_http_set_and_list_review(tmp_path) -> None:
    db_path = tmp_path / "g.db"
    rid = _seed_result(db_path)
    app = create_app(GatewayConfig(database_path=db_path, media_dir=tmp_path / "media"))
    client = TestClient(app)

    r = client.post(
        "/api/v1/tools/set_review_state",
        json={"arguments": {"result_id": rid, "review_state": "corrected", "reviewer": "qa"}},
    )
    assert r.status_code == 200 and r.json()["ok"] is True

    r2 = client.post(
        "/api/v1/tools/list_observations_for_review",
        json={"arguments": {"review_state": "corrected"}},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["ok"] is True and body["count"] == 1
