"""Species diversity report — how rich and even is the community at a site?

Standard ecology metrics over a batch of detections: **richness** (distinct subjects),
the **Shannon index** H = -Σ pᵢ·ln pᵢ, **Pielou evenness** J = H / ln(richness) (0 = one
species dominates, 1 = all equally common), and **Simpson dominance** D = Σ pᵢ² (higher =
more dominated). Answers "is this a diverse site or a one-species show?".

Pure and storage-agnostic: takes the detection dicts ``list_inference_results`` returns.
No DB or framework imports, so it unit-tests in isolation.
"""

from __future__ import annotations

import math
from typing import Any


def build_diversity_report(detections: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise species diversity from a batch of detections.

    Args:
        detections: Rows with ``top_species``/``top_label`` (timestamps unused here).

    Returns a JSON-serialisable report: ``total_detections``, ``richness``,
    ``shannon_index``, ``evenness``, ``simpson_dominance``, ``dominant_subject``, and a
    ``species`` list (most abundant first) with per-subject ``count`` and ``proportion``.
    """
    counts: dict[str, int] = {}
    total = 0
    for det in detections:
        subject = det.get("top_species") or det.get("top_label")
        if not subject:
            continue
        counts[subject] = counts.get(subject, 0) + 1
        total += 1

    richness = len(counts)
    shannon = 0.0
    simpson = 0.0
    species: list[dict[str, Any]] = []
    for subject, count in counts.items():
        p = count / total if total else 0.0
        if p > 0:
            shannon -= p * math.log(p)
        simpson += p * p
        species.append({"subject": subject, "count": count, "proportion": round(p, 4)})
    species.sort(key=lambda s: (-s["count"], s["subject"]))

    if richness > 1:
        evenness = shannon / math.log(richness)
    elif richness == 1:
        evenness = 1.0
    else:
        evenness = 0.0

    return {
        "total_detections": total,
        "richness": richness,
        "shannon_index": round(shannon, 4),
        "evenness": round(evenness, 4),
        "simpson_dominance": round(simpson, 4),
        "dominant_subject": species[0]["subject"] if species else None,
        "species": species,
    }
