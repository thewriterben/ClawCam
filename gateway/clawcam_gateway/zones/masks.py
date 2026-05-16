"""Privacy mask application for ClawCam media files.

When a device has zones with action ``privacy_mask``, those polygon
regions are blacked out in the source image before inference runs and
before the gateway stores the JPEG. This is irreversible by design — the
goal is to give operators a defensible promise that a region of frame
*never* gets persisted by ClawCam.

Implementation: PIL ImageDraw.polygon with fill=(0, 0, 0) on a copy of
the image. The polygon coordinates are normalised to [0, 1] in the DB,
so they get scaled up to the image's actual pixel dimensions here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def apply_privacy_masks(image_path: str | Path, zones: list[dict[str, Any]]) -> bool:
    """Black out every ``privacy_mask`` zone in *image_path*. Returns True on success.

    Failures are logged and reported as False; the caller should treat
    failure as "image left unmodified" — never raise into the ingest
    path because a privacy mask error must not block media storage.
    """
    privacy_zones = [
        z for z in zones
        if z.get("action") == "privacy_mask" and z.get("enabled", True)
    ]
    if not privacy_zones:
        return True

    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError:  # pragma: no cover - Pillow always installed in this project
        logger.warning("Pillow not installed; cannot apply privacy masks to %s", image_path)
        return False

    try:
        path = Path(image_path)
        with Image.open(path) as im:
            im_rgb = im.convert("RGB")
            width, height = im_rgb.size
            draw = ImageDraw.Draw(im_rgb)
            for zone in privacy_zones:
                polygon = zone.get("polygon") or []
                if len(polygon) < 3:
                    continue
                pixels = [(int(p[0] * width), int(p[1] * height)) for p in polygon]
                draw.polygon(pixels, fill=(0, 0, 0))
            im_rgb.save(path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("privacy mask application failed for %s: %s", image_path, exc)
        return False
