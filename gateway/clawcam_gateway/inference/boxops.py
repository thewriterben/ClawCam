"""Bounding-box operations for the detection pipeline — IoU, NMS, and chain fusion.

The orchestrator runs a *chain* of detectors over one image (e.g. MegaDetector to
localise an animal, then a species classifier). Each detector's result is stored on its
own, so nothing consolidates them: duplicate boxes from a single model are never
suppressed, and a classifier's species never enriches the detector's box.

This module supplies the pure geometry to do both:

* :func:`iou`             — intersection-over-union of two normalised boxes.
* :func:`nms`             — greedy non-max suppression within a detection list.
* :func:`merge_results`   — fuse a chain's :class:`InferenceResult` list into one
                            consolidated result (localisation from the detector,
                            species/label enrichment from overlapping detections).

Pure and storage-agnostic — it imports only the :class:`Detection` data model (stdlib
only), so it unit-tests in isolation without a database.
"""

from __future__ import annotations

from typing import Iterable

from .detector import Detection, InferenceResult

# A label is "generic" if it only localises without identifying the subject; a more
# specific label (anything else) or a non-null species should win during a merge.
_GENERIC_LABELS = {"animal", "object", "detection", ""}


def _area(box: list[float]) -> float:
    w = max(0.0, box[2] - box[0])
    h = max(0.0, box[3] - box[1])
    return w * h


def iou(a: list[float], b: list[float]) -> float:
    """Intersection-over-union of two ``[x1, y1, x2, y2]`` boxes. ``0.0`` if disjoint."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0.0 else 0.0


def nms(
    detections: Iterable[Detection],
    iou_threshold: float = 0.5,
    class_agnostic: bool = False,
) -> list[Detection]:
    """Greedy non-max suppression: drop lower-confidence boxes that overlap a kept one.

    By default suppression is *per label* (a "person" box never suppresses an "animal"
    box); pass ``class_agnostic=True`` to suppress across labels. Input order does not
    matter — detections are processed highest-confidence first. Returns a new list.
    """
    dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
    kept: list[Detection] = []
    for d in dets:
        overlaps = any(
            (class_agnostic or k.label == d.label) and iou(d.bbox, k.bbox) >= iou_threshold
            for k in kept
        )
        if not overlaps:
            kept.append(d)
    return kept


def _merge_cluster(cluster: list[Detection]) -> Detection:
    """Collapse a group of overlapping detections into one enriched detection."""
    anchor = max(cluster, key=lambda d: d.confidence)  # best localisation + confidence
    # Prefer a specific label over a generic one (highest-confidence specific wins).
    specific = [d for d in cluster if d.label not in _GENERIC_LABELS]
    label = max(specific, key=lambda d: d.confidence).label if specific else anchor.label
    # Attach species from the highest-confidence detection that carries one.
    with_species = [d for d in cluster if d.species]
    species = max(with_species, key=lambda d: d.confidence).species if with_species else None
    return Detection(
        label=label,
        confidence=anchor.confidence,
        bbox=list(anchor.bbox),
        species=species,
    )


def merge_results(
    results: Iterable[InferenceResult],
    iou_threshold: float = 0.5,
    model_name: str = "fused",
    model_version: str = "1",
) -> InferenceResult:
    """Fuse a detector chain's results into one consolidated :class:`InferenceResult`.

    Every detection across all ``results`` is pooled, then grouped into clusters of
    mutually-overlapping boxes (single-link at ``iou_threshold``, label-agnostic so a
    generic "animal" box and its species classification merge). Each cluster collapses to
    one detection: the highest-confidence box for localisation, the most specific label,
    and any species found in the cluster. Clusters are returned highest-confidence first.
    """
    pool: list[Detection] = [d for r in results for d in r.detections]
    clusters: list[list[Detection]] = []
    for d in pool:
        placed = False
        for cluster in clusters:
            if any(iou(d.bbox, c.bbox) >= iou_threshold for c in cluster):
                cluster.append(d)
                placed = True
                break
        if not placed:
            clusters.append([d])

    merged = [_merge_cluster(c) for c in clusters]
    merged.sort(key=lambda d: d.confidence, reverse=True)
    return InferenceResult(model_name=model_name, model_version=model_version, detections=merged)
