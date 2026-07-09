"""Imagery → land-cover primitives for ClawCam (Conservation Grid G6, imagery side).

Turns georeferenced orbital/aerial rasters into the classified land-cover grid the habitat
report consumes. Pure list math — no numpy/GDAL — so it stays unit-testable and portable.
"""

from clawcam_gateway.imagery.landcover import (
    RasterGrid,
    bbox_of,
    classify_raster,
    clip_raster,
    landcover_from_raster,
)

__all__ = [
    "RasterGrid",
    "bbox_of",
    "classify_raster",
    "clip_raster",
    "landcover_from_raster",
]
