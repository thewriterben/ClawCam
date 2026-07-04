"""Tests for the detection box-ops (pure, import-isolated).

Imports only clawcam_gateway.inference.boxops/detector (stdlib-only), so it runs in the
sandbox without touching the database layer.
"""

import pytest

from clawcam_gateway.inference.boxops import (
    fuse_detection_groups,
    iou,
    merge_results,
    nms,
)
from clawcam_gateway.inference.detector import Detection, InferenceResult


def _d(label, conf, box, species=None):
    return Detection(label=label, confidence=conf, bbox=list(box), species=species)


# ── IoU ──────────────────────────────────────────────────────────────────────

def test_iou_identical_is_one():
    assert iou([0, 0, 1, 1], [0, 0, 1, 1]) == pytest.approx(1.0)


def test_iou_disjoint_is_zero():
    assert iou([0, 0, 0.4, 0.4], [0.6, 0.6, 1.0, 1.0]) == 0.0


def test_iou_half_overlap():
    # Two unit-area-ish boxes overlapping on half → inter 0.5, union 1.5 → 1/3.
    assert iou([0, 0, 1, 2], [0, 1, 1, 3]) == pytest.approx(1 / 3)


# ── NMS ──────────────────────────────────────────────────────────────────────

def test_nms_suppresses_duplicate_same_label():
    a = _d("animal", 0.9, [0, 0, 0.5, 0.5])
    b = _d("animal", 0.6, [0.02, 0.02, 0.52, 0.52])  # heavy overlap, lower conf
    kept = nms([b, a], iou_threshold=0.5)
    assert len(kept) == 1
    assert kept[0].confidence == 0.9  # the stronger box survives


def test_nms_keeps_different_labels_by_default():
    a = _d("animal", 0.9, [0, 0, 0.5, 0.5])
    p = _d("person", 0.8, [0, 0, 0.5, 0.5])  # same box, different label
    assert len(nms([a, p], iou_threshold=0.5)) == 2
    # class-agnostic collapses them
    assert len(nms([a, p], iou_threshold=0.5, class_agnostic=True)) == 1


def test_nms_keeps_separated_boxes():
    a = _d("animal", 0.9, [0, 0, 0.3, 0.3])
    b = _d("animal", 0.8, [0.6, 0.6, 0.9, 0.9])
    assert len(nms([a, b], iou_threshold=0.5)) == 2


# ── Chain fusion ─────────────────────────────────────────────────────────────

def test_merge_enriches_generic_box_with_species():
    detector = InferenceResult("megadetector", "5", [_d("animal", 0.92, [0, 0, 0.5, 0.5])])
    classifier = InferenceResult(
        "bird_classifier", "1",
        [_d("bird", 0.80, [0.01, 0.01, 0.49, 0.49], species="American robin")],
    )
    fused = merge_results([detector, classifier], iou_threshold=0.5)
    assert len(fused.detections) == 1
    d = fused.detections[0]
    assert d.confidence == 0.92          # localisation confidence from the detector
    assert d.label == "bird"             # specific label beats generic "animal"
    assert d.species == "American robin"  # species carried over
    assert fused.model_name == "fused"


def test_merge_keeps_distinct_subjects_separate():
    r = InferenceResult(
        "megadetector", "5",
        [_d("animal", 0.9, [0, 0, 0.3, 0.3]), _d("person", 0.8, [0.6, 0.6, 0.95, 0.95])],
    )
    fused = merge_results([r], iou_threshold=0.5)
    assert len(fused.detections) == 2
    # Highest confidence first.
    assert fused.detections[0].confidence == 0.9


def test_merge_empty_results_is_empty():
    fused = merge_results([InferenceResult("m", "1", [])])
    assert fused.detections == []
    assert fused.top_label is None


def test_fuse_detection_groups_from_stored_rows():
    # Two detectors' stored detection lists (as parsed from inference_results rows).
    megadetector = [{"label": "animal", "confidence": 0.92, "bbox": [0, 0, 0.5, 0.5], "species": None}]
    classifier = [{"label": "bird", "confidence": 0.80, "bbox": [0.01, 0.0, 0.5, 0.5],
                   "species": "American robin"}]
    fused = fuse_detection_groups([megadetector, classifier], iou_threshold=0.5)
    assert fused["top_label"] == "bird"
    assert fused["top_species"] == "American robin"
    assert fused["top_confidence"] == pytest.approx(0.92)
    assert len(fused["detections"]) == 1


def test_fuse_detection_groups_handles_empty_and_missing_fields():
    fused = fuse_detection_groups([[], [{"label": "person", "confidence": 0.7, "bbox": [0, 0, 1, 1]}]])
    assert fused["top_label"] == "person"
    assert fused["top_species"] is None
    # Fully empty input → empty fused result.
    assert fuse_detection_groups([])["detections"] == []


def test_merge_prefers_highest_confidence_species():
    r = InferenceResult(
        "chain", "1",
        [
            _d("animal", 0.95, [0, 0, 0.5, 0.5]),
            _d("deer", 0.60, [0.01, 0.0, 0.5, 0.5], species="mule deer"),
            _d("deer", 0.80, [0.0, 0.01, 0.5, 0.5], species="white-tailed deer"),
        ],
    )
    fused = merge_results([r], iou_threshold=0.4)
    assert len(fused.detections) == 1
    assert fused.detections[0].species == "white-tailed deer"  # higher-conf species wins
