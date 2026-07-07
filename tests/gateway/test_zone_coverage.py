"""Tests for area-coverage zone matching (pure, import-isolated)."""

import pytest

from clawcam_gateway.zones.geometry import (
    apply_zones_to_result,
    bbox_polygon_coverage,
    zone_for_bbox,
    zone_for_bbox_coverage,
)

# A unit square covering the left half of the frame: x in [0, 0.5], y in [0, 1].
LEFT_HALF = [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]]


def test_fully_inside_is_one():
    cov = bbox_polygon_coverage([0.1, 0.1, 0.4, 0.9], LEFT_HALF)
    assert cov == pytest.approx(1.0)


def test_fully_outside_is_zero():
    cov = bbox_polygon_coverage([0.6, 0.1, 0.9, 0.9], LEFT_HALF)
    assert cov == 0.0


def test_half_straddling_edge_is_about_half():
    # bbox spans x in [0.25, 0.75]; the polygon edge is at x=0.5 → ~50% inside.
    cov = bbox_polygon_coverage([0.25, 0.2, 0.75, 0.8], LEFT_HALF)
    assert cov == pytest.approx(0.5, abs=0.06)


def test_degenerate_and_invalid_inputs():
    assert bbox_polygon_coverage([0.2, 0.2, 0.2, 0.8], LEFT_HALF) == 0.0   # zero width
    assert bbox_polygon_coverage([0.2, 0.5, 0.8, 0.5], LEFT_HALF) == 0.0   # zero height
    assert bbox_polygon_coverage([0.1, 0.1, 0.4, 0.9], [[0, 0], [1, 1]]) == 0.0  # <3 verts
    with pytest.raises(ValueError):
        bbox_polygon_coverage([0.1, 0.1, 0.4], LEFT_HALF)


def test_coverage_matcher_catches_edge_straddler_that_center_misses():
    # A subject whose center (x=0.55) is just OUTSIDE the left-half zone, but ~40%
    # of its box overlaps. Center-point test would miss it; coverage catches it.
    zones = [{"zone_id": "z1", "polygon": LEFT_HALF, "action": "alert", "priority": 1}]
    bbox = [0.35, 0.2, 0.75, 0.8]  # center x = 0.55 (outside), ~37% inside
    from clawcam_gateway.zones.geometry import zone_for_bbox
    assert zone_for_bbox(bbox, zones) is None                       # center misses
    assert zone_for_bbox_coverage(bbox, zones, min_coverage=0.3) is not None  # coverage hits
    assert zone_for_bbox_coverage(bbox, zones, min_coverage=0.6) is None      # not enough


def test_coverage_matcher_respects_priority_and_enabled():
    inner = [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]]
    zones = [
        {"zone_id": "low", "polygon": inner, "action": "alert", "priority": 5},
        {"zone_id": "high", "polygon": inner, "action": "ignore", "priority": 1},
        {"zone_id": "off", "polygon": inner, "action": "alert", "priority": 0, "enabled": False},
    ]
    bbox = [0.1, 0.1, 0.4, 0.9]  # fully inside `inner`
    z = zone_for_bbox_coverage(bbox, zones, min_coverage=0.5)
    assert z["zone_id"] == "high"  # lowest priority number among enabled wins; disabled skipped


# ── apply_zones_to_result opt-in coverage mode ───────────────────────────────

_IGNORE_LEFT = [{"zone_id": "z", "polygon": LEFT_HALF, "action": "ignore", "priority": 1}]


def _result(bbox):
    return {"detections": [{"label": "animal", "confidence": 0.9, "bbox": bbox}]}


def test_apply_default_is_center_and_keeps_edge_straddler():
    # center x = 0.55 is outside the ignore zone → default (center) mode keeps it.
    out, _ = apply_zones_to_result(_result([0.35, 0.2, 0.75, 0.8]), _IGNORE_LEFT)
    assert len(out["detections"]) == 1


def test_apply_coverage_mode_drops_edge_straddler():
    # ~37% overlap >= 0.3 → routed into the ignore zone → dropped.
    out, _ = apply_zones_to_result(_result([0.35, 0.2, 0.75, 0.8]), _IGNORE_LEFT, min_coverage=0.3)
    assert out["detections"] == []


def test_apply_coverage_threshold_too_high_keeps():
    out, _ = apply_zones_to_result(_result([0.35, 0.2, 0.75, 0.8]), _IGNORE_LEFT, min_coverage=0.6)
    assert len(out["detections"]) == 1
