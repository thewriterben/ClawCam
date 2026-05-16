"""Polygon geometry + zone action vocabulary.

All coordinates are normalised to the [0, 1] range so zones survive
re-framing or resolution changes. Polygons must have at least 3 vertices
and form a simple (non-self-intersecting) polygon — we don't validate
non-self-intersection because the cost of a buggy polygon is just a
mis-routed detection, not a corrupted database.
"""

from __future__ import annotations

from typing import Any, Iterable


# ── Action constants ─────────────────────────────────────────────────────────

ACTION_ALERT = "alert"
ACTION_RECORD = "record"
ACTION_IGNORE = "ignore"
ACTION_PRIVACY_MASK = "privacy_mask"

ZONE_ACTIONS: tuple[str, ...] = (
    ACTION_ALERT, ACTION_RECORD, ACTION_IGNORE, ACTION_PRIVACY_MASK,
)


def is_valid_zone_action(value: str | None) -> bool:
    return value in ZONE_ACTIONS


# ── Polygon validation ──────────────────────────────────────────────────────


def is_valid_polygon(polygon: Any) -> bool:
    """Return True iff *polygon* is a non-empty list of >=3 [x, y] points
    with all coordinates in [0, 1]."""
    if not isinstance(polygon, list) or len(polygon) < 3:
        return False
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return False
        x, y = point
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            return False
        if not (0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0):
            return False
    return True


# ── Geometry primitives ─────────────────────────────────────────────────────


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test.

    Returns True if *point* lies strictly inside the polygon. Boundary
    cases (point exactly on an edge or vertex) are reported as "inside"
    — that's the convention you want for "did this animal trip the
    alarm zone" decisions where edges are noise, not signal.
    """
    if not polygon or len(polygon) < 3:
        return False
    x, y = point
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        # Edge crosses the horizontal ray at y
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def bbox_center(bbox: Iterable[float]) -> tuple[float, float]:
    """Return the center point of an [x1, y1, x2, y2] bounding box."""
    coords = list(bbox)
    if len(coords) != 4:
        raise ValueError(f"bbox must have 4 elements, got {len(coords)}")
    x1, y1, x2, y2 = coords
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


# ── Zone lookup ─────────────────────────────────────────────────────────────


def zone_for_bbox(
    bbox: Iterable[float],
    zones: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the first enabled zone whose polygon contains *bbox*'s center.

    Zones are evaluated in priority order (ascending — lower priority
    number wins). When no zone contains the bbox, returns None and the
    caller falls back to default behavior (alert fires normally).
    """
    cx, cy = bbox_center(bbox)
    ordered = sorted(
        (z for z in zones if z.get("enabled", True)),
        key=lambda z: z.get("priority", 100),
    )
    for zone in ordered:
        polygon = zone.get("polygon") or []
        if point_in_polygon((cx, cy), polygon):
            return zone
    return None


# ── AlertEvaluator integration helper ───────────────────────────────────────


def apply_zones_to_result(
    inference_result: dict[str, Any],
    zones: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Filter an inference result by zone actions.

    Walks each detection in ``inference_result["detections"]``, looks up
    its zone (if any), and:

      - drops detections in ``ignore`` zones,
      - tags detections in ``record`` zones with ``"alert_blocked": True``
        so the AlertEvaluator never fires a webhook for them.

    Returns ``(filtered_result, alerts_blocked)`` — ``alerts_blocked`` is
    True if *all* surviving detections come from record-only zones, in
    which case the alert pipeline should skip the rule pass entirely.

    The result's ``top_label`` / ``top_confidence`` / ``top_species`` are
    recomputed from the surviving detections.
    """
    if not zones:
        return inference_result, False

    detections = inference_result.get("detections") or []
    if not detections:
        return inference_result, False

    kept: list[dict[str, Any]] = []
    any_record_only = False
    any_alert_eligible = False

    for det in detections:
        bbox = det.get("bbox")
        if bbox is None or len(bbox) != 4:
            kept.append(det)
            any_alert_eligible = True
            continue
        zone = zone_for_bbox(bbox, zones)
        if zone is None:
            kept.append(det)
            any_alert_eligible = True
            continue
        action = zone.get("action")
        if action == ACTION_IGNORE:
            continue   # drop entirely
        if action == ACTION_RECORD:
            kept.append({**det, "alert_blocked": True, "zone_id": zone.get("zone_id")})
            any_record_only = True
            continue
        if action == ACTION_PRIVACY_MASK:
            # Privacy masks are applied at media-write time, not detection time.
            # Treat the detection as if no zone matched (it was already masked
            # out before inference ran, so this detection probably shouldn't
            # exist — fail open).
            kept.append({**det, "zone_id": zone.get("zone_id")})
            any_alert_eligible = True
            continue
        # ACTION_ALERT or unknown — keep
        kept.append({**det, "zone_id": zone.get("zone_id")})
        any_alert_eligible = True

    # Recompute top_* fields from kept detections.
    filtered = dict(inference_result)
    filtered["detections"] = kept
    if kept:
        top = max(kept, key=lambda d: d.get("confidence", 0.0))
        filtered["top_label"] = top.get("label")
        filtered["top_confidence"] = top.get("confidence")
        filtered["top_species"] = top.get("species")
    else:
        filtered["top_label"] = None
        filtered["top_confidence"] = 0.0
        filtered["top_species"] = None

    alerts_blocked = (not any_alert_eligible) and any_record_only
    return filtered, alerts_blocked
