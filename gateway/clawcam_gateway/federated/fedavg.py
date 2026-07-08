"""Federated averaging (FedAvg) — combine per-node model updates into a global model.

Each camera node trains locally on its own review-labelled detections and reports an
*update*: its model weights plus how many samples they were trained on. FedAvg forms the
new global model as the **sample-weighted average** of those updates, so a node that
reviewed 1000 detections counts more than one that reviewed 10 — the standard, and only
data ever leaving a node is weights, never imagery.

Optionally each node also carries a **trust** multiplier (e.g. from the dynamic
trust-scoring layer), so a suspect or drifting node can be down-weighted without being
dropped. Effective weight is ``sample_count × trust``.

Pure and dependency-free (stdlib only): operates on plain dicts, so it unit-tests in
isolation and can run host-side or in a coordinator.
"""

from __future__ import annotations

from typing import Any


def federated_average(
    updates: list[dict[str, Any]],
    trust: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Aggregate per-node model updates into one global model (weighted FedAvg).

    Args:
        updates: one dict per node — ``{"node_id", "sample_count", "weights"}`` where
                 ``weights`` maps a parameter name to a list of floats. All updates must
                 share the same parameter names and per-parameter vector lengths.
        trust:   optional ``{node_id: multiplier}``; a node's effective weight is
                 ``sample_count × trust`` (default trust 1.0). Nodes with zero effective
                 weight (no samples, or trust 0) are skipped.

    Returns ``{"weights", "total_weight", "nodes", "params"}`` — the averaged global
    weights, the summed effective weight, the list of contributing node ids, and the
    parameter names.

    Raises ``ValueError`` on empty input, mismatched parameter shapes, or zero total
    weight (no node contributed).
    """
    if not updates:
        raise ValueError("no updates to aggregate")
    trust = trust or {}

    ref = updates[0].get("weights") or {}
    param_names = list(ref.keys())
    if not param_names:
        raise ValueError("first update carries no weights")
    lengths = {p: len(ref[p]) for p in param_names}

    acc: dict[str, list[float]] = {p: [0.0] * lengths[p] for p in param_names}
    total_w = 0.0
    nodes: list[str] = []

    for u in updates:
        node_id = u.get("node_id", "?")
        w = float(u.get("sample_count", 0)) * float(trust.get(node_id, 1.0))
        if w <= 0.0:
            continue
        wt = u.get("weights") or {}
        if set(wt.keys()) != set(param_names):
            raise ValueError(f"node {node_id!r}: parameter names differ from the reference update")
        for p in param_names:
            vec = wt[p]
            if len(vec) != lengths[p]:
                raise ValueError(f"node {node_id!r}: parameter {p!r} has length {len(vec)}, expected {lengths[p]}")
            col = acc[p]
            for i, v in enumerate(vec):
                col[i] += w * float(v)
        total_w += w
        nodes.append(node_id)

    if total_w <= 0.0:
        raise ValueError("total aggregation weight is zero (no node contributed)")

    weights = {
        p: [round(acc[p][i] / total_w, 6) for i in range(lengths[p])]
        for p in param_names
    }
    return {
        "weights": weights,
        "total_weight": round(total_w, 6),
        "nodes": nodes,
        "params": param_names,
    }
