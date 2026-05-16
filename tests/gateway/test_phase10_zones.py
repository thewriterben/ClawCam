"""Phase 10 tests: detection zones + privacy masks.

Coverage
--------
- Geometry primitives: point_in_polygon (inside, outside, edge),
  bbox_center, is_valid_polygon (3-pt minimum, [0,1] range)
- Zone action vocabulary + validator
- zone_for_bbox priority ordering; disabled zones skipped
- apply_zones_to_result: ignore drops, record blocks alerts,
  alert keeps + tags, recompute top_*, alerts_blocked flag
- Privacy mask image manipulation: black pixel verifying with PIL
- DB CRUD for detection_zones with polygon JSON round-trip
- AlertEvaluator integration: zone gating blocks alerts end-to-end
- REST CRUD with polygon validation + zone action validation
- MCP tools list_detection_zones (auto), create_detection_zone (gated)
- Brain adapter policy classification
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
_BRAIN_DIR = _REPO / "brain" / "oh-ben-claw-adapter"
for _p in (_GW, _BRAIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient
from PIL import Image

from clawcam_gateway.alerts.evaluator import AlertEvaluator
from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.mcp_server.stdio_server import TOOL_DEFINITIONS
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    create_detection_zone as tool_create_zone,
    list_detection_zones as tool_list_zones,
)
from clawcam_gateway.zones import (
    ACTION_ALERT,
    ACTION_IGNORE,
    ACTION_PRIVACY_MASK,
    ACTION_RECORD,
    ZONE_ACTIONS,
    apply_privacy_masks,
    apply_zones_to_result,
    bbox_center,
    is_valid_polygon,
    is_valid_zone_action,
    point_in_polygon,
    zone_for_bbox,
)
from clawcam_adapter import ToolPolicy  # type: ignore[import]


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _seed_device(db: GatewayDatabase, device_id: str = "cam-p10") -> None:
    db.upsert_device({
        "device_id": device_id,
        "device_type": "node",
        "name": "Zone Test Camera",
        "status": "active",
        "created_at": "2026-05-15T00:00:00Z",
        "last_seen_at": "2026-05-15T00:00:00Z",
    })


@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "test.db")
    _seed_device(db)
    return db


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, GatewayDatabase]:
    cfg = GatewayConfig(database_path=tmp_path / "test.db",
                        media_dir=tmp_path / "media")
    app = create_app(config=cfg)
    db = GatewayDatabase(cfg.database_path)
    _seed_device(db)
    return TestClient(app), db


SQUARE_FULL = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]   # whole frame
SQUARE_TL = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]      # top-left quarter
SQUARE_BR = [[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0]]      # bottom-right quarter


# ── Geometry primitives ─────────────────────────────────────────────────────

class TestGeometry:
    def test_point_inside(self):
        assert point_in_polygon((0.25, 0.25), SQUARE_TL)

    def test_point_outside(self):
        assert not point_in_polygon((0.75, 0.75), SQUARE_TL)

    def test_point_outside_below(self):
        assert not point_in_polygon((0.25, 0.9), SQUARE_TL)

    def test_empty_polygon(self):
        assert not point_in_polygon((0.5, 0.5), [])

    def test_two_point_polygon_rejected(self):
        assert not point_in_polygon((0.5, 0.5), [[0, 0], [1, 0]])

    def test_triangle_inside(self):
        triangle = [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]
        assert point_in_polygon((0.5, 0.4), triangle)
        # Point well outside the triangle on the side
        assert not point_in_polygon((0.05, 0.9), triangle)

    def test_bbox_center(self):
        assert bbox_center([0, 0, 1, 1]) == (0.5, 0.5)
        assert bbox_center([0.2, 0.2, 0.6, 0.6]) == pytest.approx((0.4, 0.4))

    def test_bbox_center_wrong_length(self):
        with pytest.raises(ValueError):
            bbox_center([0, 0, 1])


class TestPolygonValidation:
    def test_valid(self):
        assert is_valid_polygon(SQUARE_FULL)

    def test_too_few_points(self):
        assert not is_valid_polygon([[0, 0], [1, 1]])

    def test_out_of_range(self):
        assert not is_valid_polygon([[0, 0], [1.5, 0], [0, 1]])

    def test_negative(self):
        assert not is_valid_polygon([[-0.1, 0], [1, 0], [0, 1]])

    def test_wrong_shape(self):
        assert not is_valid_polygon([[0, 0, 0], [1, 0], [0, 1]])

    def test_not_a_list(self):
        assert not is_valid_polygon("nope")
        assert not is_valid_polygon(None)


# ── Zone vocabulary ─────────────────────────────────────────────────────────

class TestZoneActions:
    def test_action_set(self):
        assert set(ZONE_ACTIONS) == {
            ACTION_ALERT, ACTION_RECORD, ACTION_IGNORE, ACTION_PRIVACY_MASK,
        }

    def test_validator(self):
        assert is_valid_zone_action(ACTION_IGNORE)
        assert not is_valid_zone_action("delete")


# ── zone_for_bbox ───────────────────────────────────────────────────────────

class TestZoneForBbox:
    def test_no_zones_returns_none(self):
        assert zone_for_bbox([0, 0, 1, 1], []) is None

    def test_picks_priority_winner(self):
        zones = [
            {"zone_id": "lo", "polygon": SQUARE_FULL, "action": ACTION_ALERT,
             "priority": 200, "enabled": True},
            {"zone_id": "hi", "polygon": SQUARE_FULL, "action": ACTION_IGNORE,
             "priority": 10, "enabled": True},
        ]
        winner = zone_for_bbox([0.4, 0.4, 0.6, 0.6], zones)
        assert winner["zone_id"] == "hi"

    def test_skips_disabled(self):
        zones = [
            {"zone_id": "off", "polygon": SQUARE_FULL, "action": ACTION_IGNORE,
             "priority": 10, "enabled": False},
            {"zone_id": "on", "polygon": SQUARE_FULL, "action": ACTION_ALERT,
             "priority": 100, "enabled": True},
        ]
        winner = zone_for_bbox([0.5, 0.5, 0.6, 0.6], zones)
        assert winner["zone_id"] == "on"

    def test_bbox_outside_all_polygons(self):
        zones = [{"zone_id": "tl", "polygon": SQUARE_TL, "action": ACTION_ALERT,
                  "priority": 1, "enabled": True}]
        assert zone_for_bbox([0.7, 0.7, 0.9, 0.9], zones) is None


# ── apply_zones_to_result ───────────────────────────────────────────────────

class TestApplyZonesToResult:
    @staticmethod
    def _result(detections):
        return {
            "detections": detections,
            "top_label": detections[0]["label"] if detections else None,
            "top_confidence": detections[0]["confidence"] if detections else 0.0,
            "top_species": detections[0].get("species") if detections else None,
        }

    def test_no_zones_unchanged(self):
        r = self._result([{"label": "animal", "confidence": 0.9, "bbox": [0, 0, 1, 1]}])
        filtered, blocked = apply_zones_to_result(r, [])
        assert filtered == r
        assert not blocked

    def test_ignore_zone_drops_detection(self):
        zones = [{"zone_id": "z", "polygon": SQUARE_FULL,
                  "action": ACTION_IGNORE, "priority": 1, "enabled": True}]
        r = self._result([{"label": "animal", "confidence": 0.9, "bbox": [0.2, 0.2, 0.4, 0.4]}])
        filtered, _ = apply_zones_to_result(r, zones)
        assert filtered["detections"] == []
        assert filtered["top_confidence"] == 0.0

    def test_record_zone_blocks_alert(self):
        zones = [{"zone_id": "z", "polygon": SQUARE_FULL,
                  "action": ACTION_RECORD, "priority": 1, "enabled": True}]
        r = self._result([{"label": "animal", "confidence": 0.9, "bbox": [0.4, 0.4, 0.6, 0.6]}])
        filtered, blocked = apply_zones_to_result(r, zones)
        assert blocked is True
        assert filtered["detections"][0]["alert_blocked"] is True

    def test_alert_zone_keeps_detection(self):
        zones = [{"zone_id": "z", "polygon": SQUARE_FULL,
                  "action": ACTION_ALERT, "priority": 1, "enabled": True}]
        r = self._result([{"label": "animal", "confidence": 0.9, "bbox": [0.4, 0.4, 0.6, 0.6]}])
        filtered, blocked = apply_zones_to_result(r, zones)
        assert blocked is False
        assert filtered["detections"][0]["zone_id"] == "z"

    def test_mixed_zones_blocked_only_when_all_record(self):
        zones = [
            {"zone_id": "tl-rec", "polygon": SQUARE_TL,
             "action": ACTION_RECORD, "priority": 1, "enabled": True},
            {"zone_id": "br-alert", "polygon": SQUARE_BR,
             "action": ACTION_ALERT, "priority": 1, "enabled": True},
        ]
        r = self._result([
            {"label": "person", "confidence": 0.9, "bbox": [0.1, 0.1, 0.2, 0.2]},
            {"label": "vehicle", "confidence": 0.8, "bbox": [0.8, 0.8, 0.9, 0.9]},
        ])
        filtered, blocked = apply_zones_to_result(r, zones)
        assert not blocked
        assert len(filtered["detections"]) == 2

    def test_recomputes_top_label_after_drop(self):
        zones = [{"zone_id": "tl", "polygon": SQUARE_TL,
                  "action": ACTION_IGNORE, "priority": 1, "enabled": True}]
        r = self._result([
            {"label": "person", "confidence": 0.99, "bbox": [0.1, 0.1, 0.2, 0.2]},   # dropped
            {"label": "animal", "confidence": 0.5, "bbox": [0.8, 0.8, 0.9, 0.9]},     # kept
        ])
        filtered, _ = apply_zones_to_result(r, zones)
        assert filtered["top_label"] == "animal"
        assert filtered["top_confidence"] == 0.5


# ── Privacy mask application ────────────────────────────────────────────────

class TestPrivacyMasks:
    def test_no_privacy_zones_noop(self, tmp_path: Path):
        img_path = tmp_path / "x.jpg"
        Image.new("RGB", (100, 100), color=(200, 100, 50)).save(img_path)
        ok = apply_privacy_masks(img_path, [
            {"action": ACTION_ALERT, "polygon": SQUARE_FULL, "enabled": True},
        ])
        assert ok
        # Pixel still original color
        with Image.open(img_path) as im:
            assert im.getpixel((50, 50)) == (200, 100, 50)

    def test_blacks_out_polygon(self, tmp_path: Path):
        img_path = tmp_path / "y.jpg"
        Image.new("RGB", (100, 100), color=(255, 255, 255)).save(img_path)
        ok = apply_privacy_masks(img_path, [
            {"action": ACTION_PRIVACY_MASK, "polygon": SQUARE_BR, "enabled": True},
        ])
        assert ok
        with Image.open(img_path) as im:
            # Bottom-right corner should now be (or be very near) black
            r, g, b = im.getpixel((90, 90))
            assert max(r, g, b) < 20
            # Top-left corner untouched
            r, g, b = im.getpixel((10, 10))
            assert min(r, g, b) > 200

    def test_invalid_image_returns_false_does_not_raise(self, tmp_path: Path):
        bad = tmp_path / "broken.jpg"
        bad.write_bytes(b"not an image")
        ok = apply_privacy_masks(bad, [
            {"action": ACTION_PRIVACY_MASK, "polygon": SQUARE_FULL, "enabled": True},
        ])
        assert ok is False

    def test_disabled_privacy_zone_skipped(self, tmp_path: Path):
        img_path = tmp_path / "z.jpg"
        Image.new("RGB", (50, 50), color=(255, 255, 255)).save(img_path)
        apply_privacy_masks(img_path, [
            {"action": ACTION_PRIVACY_MASK, "polygon": SQUARE_FULL, "enabled": False},
        ])
        with Image.open(img_path) as im:
            assert im.getpixel((25, 25)) == (255, 255, 255)


# ── Database CRUD ───────────────────────────────────────────────────────────

class TestZonesDB:
    def test_add_and_get(self, tmp_db: GatewayDatabase):
        tmp_db.add_detection_zone({
            "zone_id": "z1",
            "device_id": "cam-p10",
            "name": "front yard",
            "polygon": SQUARE_TL,
            "action": ACTION_ALERT,
            "priority": 50,
            "enabled": True,
        })
        d = tmp_db.get_detection_zone("z1")
        assert d is not None
        assert d["polygon"] == SQUARE_TL
        assert d["action"] == ACTION_ALERT
        assert d["enabled"] is True

    def test_list_filter_by_device(self, tmp_db: GatewayDatabase):
        tmp_db.upsert_device({
            "device_id": "cam-other", "device_type": "node",
            "name": "other", "status": "active",
            "created_at": "2026-05-15T00:00:00Z",
            "last_seen_at": "2026-05-15T00:00:00Z",
        })
        tmp_db.add_detection_zone({
            "zone_id": "z-a", "device_id": "cam-p10", "name": "a",
            "polygon": SQUARE_TL, "action": ACTION_ALERT,
        })
        tmp_db.add_detection_zone({
            "zone_id": "z-b", "device_id": "cam-other", "name": "b",
            "polygon": SQUARE_BR, "action": ACTION_IGNORE,
        })
        cam = tmp_db.list_detection_zones(device_id="cam-p10")
        assert len(cam) == 1
        assert cam[0]["zone_id"] == "z-a"

    def test_update(self, tmp_db: GatewayDatabase):
        tmp_db.add_detection_zone({
            "zone_id": "z-up", "device_id": "cam-p10", "name": "old",
            "polygon": SQUARE_TL, "action": ACTION_ALERT,
        })
        assert tmp_db.update_detection_zone("z-up",
                                             {"name": "new", "action": ACTION_IGNORE,
                                              "enabled": False})
        d = tmp_db.get_detection_zone("z-up")
        assert d["name"] == "new"
        assert d["action"] == ACTION_IGNORE
        assert d["enabled"] is False

    def test_delete(self, tmp_db: GatewayDatabase):
        tmp_db.add_detection_zone({
            "zone_id": "z-del", "device_id": "cam-p10", "name": "x",
            "polygon": SQUARE_FULL, "action": ACTION_ALERT,
        })
        assert tmp_db.delete_detection_zone("z-del")
        assert tmp_db.get_detection_zone("z-del") is None

    def test_priority_ordering(self, tmp_db: GatewayDatabase):
        tmp_db.add_detection_zone({"zone_id": "p100", "device_id": "cam-p10",
                                    "name": "n", "polygon": SQUARE_FULL,
                                    "action": ACTION_ALERT, "priority": 100})
        tmp_db.add_detection_zone({"zone_id": "p1", "device_id": "cam-p10",
                                    "name": "n", "polygon": SQUARE_FULL,
                                    "action": ACTION_ALERT, "priority": 1})
        zones = tmp_db.list_detection_zones(device_id="cam-p10")
        assert zones[0]["zone_id"] == "p1"
        assert zones[1]["zone_id"] == "p100"


# ── AlertEvaluator integration ──────────────────────────────────────────────

class TestEvaluatorZoneIntegration:
    def _seed_event_and_inference(self, db: GatewayDatabase, bbox):
        db.add_event({
            "event_id": "evt-zone-1",
            "event_type": "motion_detected",
            "device_id": "cam-p10",
            "timestamp": "2026-05-15T10:00:00Z",
            "time_source": "rtc",
            "source": "node",
            "media": [],
            "metadata": {},
        })
        db.save_inference_result(
            "evt-zone-1", "/m/x.jpg",
            InferenceResult(
                model_name="mock", model_version="1",
                detections=[Detection("person", 0.9, list(bbox), None)],
            ),
        )

    def test_ignore_zone_blocks_alert(self, tmp_db: GatewayDatabase):
        self._seed_event_and_inference(tmp_db, [0.1, 0.1, 0.2, 0.2])
        tmp_db.add_detection_zone({
            "zone_id": "ignore-tl",
            "device_id": "cam-p10",
            "name": "ignore top-left",
            "polygon": SQUARE_TL,
            "action": ACTION_IGNORE,
        })
        tmp_db.add_alert_rule({
            "rule_id": "alert-people",
            "name": "people",
            "label": "person",
            "min_confidence": 0.5,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        assert evaluator.evaluate("evt-zone-1", device_id="cam-p10") == 0

    def test_record_zone_blocks_alert(self, tmp_db: GatewayDatabase):
        self._seed_event_and_inference(tmp_db, [0.1, 0.1, 0.2, 0.2])
        tmp_db.add_detection_zone({
            "zone_id": "record-tl",
            "device_id": "cam-p10",
            "name": "record tl",
            "polygon": SQUARE_TL,
            "action": ACTION_RECORD,
        })
        tmp_db.add_alert_rule({
            "rule_id": "alert-people",
            "name": "people",
            "label": "person",
            "min_confidence": 0.5,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        assert evaluator.evaluate("evt-zone-1", device_id="cam-p10") == 0

    def test_alert_zone_fires_alert(self, tmp_db: GatewayDatabase):
        self._seed_event_and_inference(tmp_db, [0.1, 0.1, 0.2, 0.2])
        tmp_db.add_detection_zone({
            "zone_id": "alert-tl",
            "device_id": "cam-p10",
            "name": "alert tl",
            "polygon": SQUARE_TL,
            "action": ACTION_ALERT,
        })
        tmp_db.add_alert_rule({
            "rule_id": "rule-fire",
            "name": "fire",
            "label": "person",
            "min_confidence": 0.5,
            "enabled": True,
        })
        evaluator = AlertEvaluator(tmp_db)
        assert evaluator.evaluate("evt-zone-1", device_id="cam-p10") == 1


# ── REST surface ────────────────────────────────────────────────────────────

class TestZonesREST:
    def test_create_zone(self, client):
        c, _ = client
        resp = c.post("/api/v1/zones", json={"data": {
            "device_id": "cam-p10",
            "name": "front yard",
            "polygon": SQUARE_TL,
            "action": ACTION_ALERT,
        }})
        assert resp.status_code == 200
        assert "zone_id" in resp.json()["zone"]

    def test_create_invalid_polygon_400(self, client):
        c, _ = client
        resp = c.post("/api/v1/zones", json={"data": {
            "device_id": "cam-p10", "name": "x",
            "polygon": [[0, 0], [1, 1]],
            "action": ACTION_ALERT,
        }})
        assert resp.status_code == 400

    def test_create_invalid_action_400(self, client):
        c, _ = client
        resp = c.post("/api/v1/zones", json={"data": {
            "device_id": "cam-p10", "name": "x",
            "polygon": SQUARE_FULL, "action": "explode",
        }})
        assert resp.status_code == 400

    def test_create_unknown_device_404(self, client):
        c, _ = client
        resp = c.post("/api/v1/zones", json={"data": {
            "device_id": "ghost", "name": "x",
            "polygon": SQUARE_FULL, "action": ACTION_ALERT,
        }})
        assert resp.status_code == 404

    def test_list_filter_device(self, client):
        c, _ = client
        c.post("/api/v1/zones", json={"data": {
            "device_id": "cam-p10", "name": "a",
            "polygon": SQUARE_TL, "action": ACTION_ALERT,
        }})
        body = c.get("/api/v1/zones?device_id=cam-p10").json()
        assert body["count"] == 1

    def test_patch_zone(self, client):
        c, _ = client
        create = c.post("/api/v1/zones", json={"data": {
            "device_id": "cam-p10", "name": "old",
            "polygon": SQUARE_TL, "action": ACTION_ALERT,
        }}).json()
        zid = create["zone"]["zone_id"]
        resp = c.patch(f"/api/v1/zones/{zid}", json={"data": {"name": "new"}})
        assert resp.status_code == 200
        assert resp.json()["zone"]["name"] == "new"

    def test_delete_zone(self, client):
        c, _ = client
        create = c.post("/api/v1/zones", json={"data": {
            "device_id": "cam-p10", "name": "x",
            "polygon": SQUARE_FULL, "action": ACTION_ALERT,
        }}).json()
        zid = create["zone"]["zone_id"]
        assert c.delete(f"/api/v1/zones/{zid}").status_code == 200
        assert c.get(f"/api/v1/zones/{zid}").status_code == 404


# ── MCP tools ───────────────────────────────────────────────────────────────

class TestZoneTools:
    def test_list_zones_empty(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        assert tool_list_zones(ctx)["count"] == 0

    def test_create_zone_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_zone(
            ctx, device_id="cam-p10", name="zone",
            polygon=SQUARE_TL, action=ACTION_ALERT,
        )
        assert result["ok"]
        assert "zone_id" in result["zone"]

    def test_create_unknown_device(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_zone(
            ctx, device_id="ghost", name="x",
            polygon=SQUARE_FULL, action=ACTION_ALERT,
        )
        assert not result["ok"]

    def test_create_invalid_polygon(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_create_zone(
            ctx, device_id="cam-p10", name="x",
            polygon=[[0, 0], [1, 1]], action=ACTION_ALERT,
        )
        assert not result["ok"]


# ── Dispatch + stdio + adapter ──────────────────────────────────────────────

class TestPhase10Wiring:
    def test_dispatch_list_zones(self, tmp_db: GatewayDatabase):
        assert dispatch_tool("list_detection_zones", {}, database_path=tmp_db.path)["ok"]

    def test_dispatch_create_zone(self, tmp_db: GatewayDatabase):
        result = dispatch_tool(
            "create_detection_zone",
            {"device_id": "cam-p10", "name": "x",
             "polygon": SQUARE_FULL, "action": ACTION_ALERT},
            database_path=tmp_db.path,
        )
        assert result["ok"]

    def test_stdio_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "list_detection_zones" in names
        assert "create_detection_zone" in names

    def test_brain_adapter_policy(self):
        policy = ToolPolicy()
        assert policy.is_auto_approved("list_detection_zones")
        assert policy.requires_approval("create_detection_zone")
