"""Pure tests for the imagery → land-cover builder (Conservation Grid G6)."""

from __future__ import annotations

import math

import pytest

from clawcam_gateway.analytics.habitat import build_habitat_report
from clawcam_gateway.imagery.landcover import (
    RasterGrid,
    bbox_of,
    classify_raster,
    clip_raster,
    landcover_from_raster,
)

# NDVI-style breaks: below 0.1 water, 0.1–0.25 bare, 0.25–0.5 grassland, else forest.
BREAKS = [(0.1, "water"), (0.25, "bare"), (0.5, "grassland")]
ABOVE = "forest"


def test_classify_thresholds_each_cell():
    r = RasterGrid(0.0, 0.0, 0.01, [[0.05, 0.2], [0.4, 0.8]])
    lc = classify_raster(r, BREAKS, ABOVE)
    assert lc.rows == [["water", "bare"], ["grassland", "forest"]]
    # LandCover keeps the raster's georeference.
    assert (lc.origin_lat, lc.origin_lon, lc.step) == (0.0, 0.0, 0.01)


def test_boundary_values_take_the_upper_class():
    # v == upper is NOT < upper, so it falls to the next class up.
    r = RasterGrid(0.0, 0.0, 1.0, [[0.1, 0.25, 0.5]])
    lc = classify_raster(r, BREAKS, ABOVE)
    assert lc.rows == [["bare", "grassland", "forest"]]


def test_unsorted_breaks_are_handled():
    r = RasterGrid(0.0, 0.0, 1.0, [[0.05, 0.4]])
    shuffled = [(0.5, "grassland"), (0.1, "water"), (0.25, "bare")]
    lc = classify_raster(r, shuffled, ABOVE)
    assert lc.rows == [["water", "grassland"]]


def test_bbox_of_points():
    pts = [(45.0, -122.0), (45.2, -121.8), (44.9, -122.1)]
    assert bbox_of(pts) == (44.9, -122.1, 45.2, -121.8)


def test_bbox_of_empty_raises():
    with pytest.raises(ValueError):
        bbox_of([])


def test_clip_selects_the_interior_window():
    # 4x4 grid at origin (0,0) step 1 => coords 0..3 on each axis.
    vals = [[float(r * 10 + c) for c in range(4)] for r in range(4)]
    r = RasterGrid(0.0, 0.0, 1.0, vals)
    clipped = clip_raster(r, 1.0, 1.0, 2.0, 2.0)
    # Keeps rows/cols 1..2; origin shifts to (1,1).
    assert clipped.origin_lat == 1.0 and clipped.origin_lon == 1.0
    assert clipped.shape() == (2, 2)
    assert clipped.values == [[11.0, 12.0], [21.0, 22.0]]


def test_clip_empty_box_raises():
    r = RasterGrid(0.0, 0.0, 1.0, [[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(ValueError):
        clip_raster(r, 10.0, 10.0, 20.0, 20.0)


def test_landcover_from_raster_dict_with_bbox():
    vals = [[0.05, 0.05, 0.05], [0.05, 0.8, 0.8], [0.05, 0.8, 0.8]]
    raster = {"origin_lat": 0.0, "origin_lon": 0.0, "step": 1.0, "values": vals}
    lc = landcover_from_raster(raster, BREAKS, ABOVE, bbox=(1.0, 1.0, 2.0, 2.0))
    assert lc.rows == [["forest", "forest"], ["forest", "forest"]]
    assert (lc.origin_lat, lc.origin_lon) == (1.0, 1.0)


def test_classified_landcover_feeds_habitat_report():
    # A raster that's forest in the north, grassland in the south.
    vals = [[0.8, 0.8], [0.8, 0.8], [0.3, 0.3], [0.3, 0.3]]
    r = RasterGrid(0.0, 0.0, 1.0, vals)
    lc = classify_raster(r, BREAKS, ABOVE)
    # Detections: 3 in forest cells (north, lat~0-1), 1 in grassland (south, lat~3).
    dets = [
        {"latitude": 0.0, "longitude": 0.0, "top_species": "marten"},
        {"latitude": 1.0, "longitude": 1.0, "top_species": "marten"},
        {"latitude": 0.0, "longitude": 1.0, "top_species": "marten"},
        {"latitude": 3.0, "longitude": 0.0, "top_species": "hare"},
    ]
    report = build_habitat_report(dets, lc, top_n=2)
    classes = {c["class"]: c for c in report["classes"]}
    assert "forest" in classes and "grassland" in classes
    # Forest is used more than its availability => selection ratio > 1.
    assert classes["forest"]["selection_ratio"] > 1.0
    assert report["located"] == 4
