"""Polygon detection zones and privacy masks for ClawCam gateway.

A *detection zone* is a polygon drawn on a camera's image with a per-zone
action that gates how detections inside it are treated:

  - ``alert``        : fire alert rules normally for detections inside this zone
  - ``record``       : keep the detection on record but never fire an alert
  - ``ignore``       : drop the detection entirely (e.g. the public sidewalk)
  - ``privacy_mask`` : black out this polygon in the stored image before any
                      detector runs (e.g. the neighbor's window)

Polygons are stored as lists of ``[x, y]`` points in **image-normalised**
coordinates (each value in the [0, 1] range). That makes them resolution-
independent so a 1080p re-frame doesn't invalidate every zone in the system.

The AlertEvaluator consults zones during alert evaluation: detections in
``ignore`` zones are filtered out, detections in ``record`` zones never
trigger webhook delivery, and detections in ``alert`` zones (or in no zone
at all) flow through to rule matching as usual.

Privacy masks are applied at media-upload time, before the JPEG is written
to disk — there is intentionally no way to recover the original.
"""

from clawcam_gateway.zones.geometry import (
    ACTION_ALERT,
    ACTION_IGNORE,
    ACTION_PRIVACY_MASK,
    ACTION_RECORD,
    ZONE_ACTIONS,
    apply_zones_to_result,
    bbox_center,
    is_valid_polygon,
    is_valid_zone_action,
    point_in_polygon,
    zone_for_bbox,
)
from clawcam_gateway.zones.masks import apply_privacy_masks

__all__ = [
    "ACTION_ALERT",
    "ACTION_IGNORE",
    "ACTION_PRIVACY_MASK",
    "ACTION_RECORD",
    "ZONE_ACTIONS",
    "apply_privacy_masks",
    "apply_zones_to_result",
    "bbox_center",
    "is_valid_polygon",
    "is_valid_zone_action",
    "point_in_polygon",
    "zone_for_bbox",
]
