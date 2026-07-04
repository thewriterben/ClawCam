"""Review triage — rank detections by how much they need a human look.

The review queue surfaces unreviewed detections, but chronological order buries the ones
that matter. A confident "white-tailed deer" at 0.98 needs no attention; a 0.45 "animal"
with no species, or a rare-species hit, does. This scores each detection for review
priority so the queue can lead with the uncertain and the unusual.

Pure and storage-agnostic — operates on already-fetched detection dicts (the shape the DB
returns), so it unit-tests in isolation without a database.
"""

from __future__ import annotations

from typing import Any, Iterable

_EMPTY_LABELS = {"", "empty", "none", "no_detection"}


def review_priority(
    row: dict[str, Any],
    low_conf: float = 0.4,
    high_conf: float = 0.75,
    rare_species: Iterable[str] = (),
) -> dict[str, Any]:
    """Score one detection row for review priority.

    Args:
        row:          Detection dict with ``top_confidence``, ``top_label``, ``top_species``.
        low_conf:     Below this, a detection is likely noise (low review value).
        high_conf:    At/above this, a detection is confident (low review value). Between
                      ``low_conf`` and ``high_conf`` is the ambiguous band that most needs review.
        rare_species: Species names that should always be bumped up for confirmation.

    Returns ``{priority, score, reasons}`` where ``priority`` is ``high``/``medium``/``low``.
    """
    conf = float(row.get("top_confidence") or 0.0)
    label = str(row.get("top_label") or "").strip().lower()
    species = row.get("top_species")
    rare = {s.strip().lower() for s in rare_species if s}

    if label in _EMPTY_LABELS:
        return {"priority": "low", "score": 0.0, "reasons": ["no detection"]}

    score = 0.0
    reasons: list[str] = []

    if low_conf <= conf < high_conf:
        score += 0.6
        reasons.append("borderline confidence")
    elif conf < low_conf:
        score += 0.2
        reasons.append("very low confidence")
    # conf >= high_conf contributes nothing — it's a confident call.

    if label == "animal" and not species:
        score += 0.3
        reasons.append("unidentified species")

    if species and str(species).strip().lower() in rare:
        score += 0.4
        reasons.append(f"rare species: {species}")

    priority = "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"
    return {"priority": priority, "score": round(score, 3), "reasons": reasons}


def build_review_queue(
    rows: list[dict[str, Any]],
    low_conf: float = 0.4,
    high_conf: float = 0.75,
    rare_species: Iterable[str] = (),
) -> dict[str, Any]:
    """Rank detection rows for review, highest-priority first.

    Each item carries the row's identity (``result_id``, ``event_id``, ``top_label``,
    ``top_species``, ``top_confidence``) plus its ``priority``, ``score``, and ``reasons``.
    Also returns per-priority counts. Ties break by ascending confidence (least certain
    first) then by ``result_id`` for stability.
    """
    items: list[dict[str, Any]] = []
    for r in rows:
        verdict = review_priority(r, low_conf=low_conf, high_conf=high_conf, rare_species=rare_species)
        items.append({
            "result_id": r.get("result_id"),
            "event_id": r.get("event_id"),
            "top_label": r.get("top_label"),
            "top_species": r.get("top_species"),
            "top_confidence": r.get("top_confidence"),
            **verdict,
        })

    items.sort(
        key=lambda x: (
            -x["score"],
            float(x["top_confidence"] or 0.0),
            str(x["result_id"] or ""),
        )
    )
    counts = {"high": 0, "medium": 0, "low": 0}
    for it in items:
        counts[it["priority"]] += 1
    return {
        "total": len(items),
        "counts": counts,
        "needs_review": counts["high"] + counts["medium"],
        "items": items,
    }
