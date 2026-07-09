"""Orbital imagery → classified land cover (Conservation Grid G6, imagery side).

Closes the loop back to the G7 habitat report. A satellite/aerial raster arrives as a
georeferenced grid of *continuous* values (e.g. NDVI, a spectral band, an elevation
model); this module clips it to a survey area and thresholds it into the discrete
land-cover classes that :class:`clawcam_gateway.analytics.habitat.LandCover` — and thus
``build_habitat_report`` — consumes. So "which habitats do the animals prefer?" can be
answered from imagery, not just a hand-drawn map.

Pure and dependency-free (no numpy/GDAL): a fetcher hands in the raster as nested lists;
everything here is deterministic list math, unit-testable in isolation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from clawcam_gateway.analytics.habitat import LandCover


@dataclass
class RasterGrid:
    """A georeferenced raster of continuous values on a regular lat/lon grid.

    ``values[r][c]`` is the value at ``lat = origin_lat + r*step``,
    ``lon = origin_lon + c*step`` — the same cell convention as
    :class:`~clawcam_gateway.analytics.habitat.LandCover`, so a classified raster drops
    straight into the habitat report.
    """

    origin_lat: float
    origin_lon: float
    step: float
    values: list[list[float]]

    def shape(self) -> tuple[int, int]:
        """(rows, cols); cols is the width of the first row (0 if empty)."""
        return (len(self.values), len(self.values[0]) if self.values else 0)


def bbox_of(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Bounding box ``(min_lat, min_lon, max_lat, max_lon)`` of ``(lat, lon)`` points."""
    if not points:
        raise ValueError("bbox_of needs at least one point")
    lats = [float(p[0]) for p in points]
    lons = [float(p[1]) for p in points]
    return (min(lats), min(lons), max(lats), max(lons))


def classify_raster(
    raster: RasterGrid,
    breaks: list[tuple[float, str]],
    above_label: str,
) -> LandCover:
    """Threshold a continuous raster into a classified :class:`LandCover`.

    ``breaks`` is a list of ``(upper, label)`` in ascending ``upper`` order; a cell value
    ``v`` takes the label of the first break with ``v < upper``. Values at or above every
    break get ``above_label``. Example (NDVI): ``[(0.1, "water"), (0.25, "bare"),
    (0.5, "grassland")]`` with ``above_label="forest"``.
    """
    ordered = sorted(breaks, key=lambda b: b[0])
    rows: list[list[str]] = []
    for row in raster.values:
        out: list[str] = []
        for v in row:
            label = above_label
            for upper, name in ordered:
                if v < upper:
                    label = name
                    break
            out.append(label)
        rows.append(out)
    return LandCover(
        origin_lat=raster.origin_lat,
        origin_lon=raster.origin_lon,
        step=raster.step,
        rows=rows,
    )


def clip_raster(
    raster: RasterGrid,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> RasterGrid:
    """Restrict a raster to the cells whose centres fall within a lat/lon bounding box.

    Returns a new :class:`RasterGrid` whose ``origin`` is shifted to the first kept cell.
    Raises ``ValueError`` if the box selects no cells or the step is non-positive.
    """
    if raster.step <= 0:
        raise ValueError("raster.step must be positive")
    nrows, ncols = raster.shape()
    if nrows == 0 or ncols == 0:
        raise ValueError("empty raster")

    # Cell index i maps to coord = origin + i*step. Keep i where min <= coord <= max, i.e.
    # ceil((min-origin)/step) <= i <= floor((max-origin)/step), clamped to the grid.
    def index_range(origin: float, lo: float, hi: float, n: int) -> tuple[int, int]:
        r0 = max(0, math.ceil((lo - origin) / raster.step - 1e-9))
        r1 = min(n - 1, math.floor((hi - origin) / raster.step + 1e-9))
        return (r0, r1)

    r0, r1 = index_range(raster.origin_lat, min_lat, max_lat, nrows)
    c0, c1 = index_range(raster.origin_lon, min_lon, max_lon, ncols)
    if r0 > r1 or c0 > c1:
        raise ValueError("bounding box selects no cells")

    sub = [row[c0 : c1 + 1] for row in raster.values[r0 : r1 + 1]]
    return RasterGrid(
        origin_lat=raster.origin_lat + r0 * raster.step,
        origin_lon=raster.origin_lon + c0 * raster.step,
        step=raster.step,
        values=sub,
    )


def landcover_from_raster(
    raster: dict[str, Any] | RasterGrid,
    breaks: list[tuple[float, str]],
    above_label: str,
    bbox: tuple[float, float, float, float] | None = None,
) -> LandCover:
    """Convenience: (optionally clip, then) classify a raster into a :class:`LandCover`.

    ``raster`` may be a :class:`RasterGrid` or a plain dict with ``origin_lat``,
    ``origin_lon``, ``step``, ``values``. ``bbox`` (min_lat, min_lon, max_lat, max_lon)
    clips first when given.
    """
    if isinstance(raster, dict):
        raster = RasterGrid(
            origin_lat=float(raster["origin_lat"]),
            origin_lon=float(raster["origin_lon"]),
            step=float(raster["step"]),
            values=[[float(v) for v in row] for row in raster["values"]],
        )
    if bbox is not None:
        raster = clip_raster(raster, *bbox)
    return classify_raster(raster, breaks, above_label)
