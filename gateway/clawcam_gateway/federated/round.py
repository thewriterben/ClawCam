"""Federated round loop — review labels → local update → aggregate → global model (G9).

Closes the federated-learning loop on top of two pieces already built: each node turns its
*human-review labels* into a local model update (here, the review-grounded confidence
threshold from the calibration report), those updates are combined by
[`federated_average`][clawcam_gateway.federated.fedavg], and the result is stamped as the
next versioned global model. Only thresholds/weights and sample counts move between nodes —
never raw imagery or detections.

Pure: composes the calibration and FedAvg builders, no DB or framework imports.
"""

from __future__ import annotations

from typing import Any

from clawcam_gateway.analytics.calibration import build_calibration_report
from clawcam_gateway.federated.fedavg import federated_average


def build_local_update(
    node_id: str,
    reviewed_rows: list[dict[str, Any]],
    target_precision: float = 0.9,
) -> dict[str, Any]:
    """A node's local model update from its reviewed detections.

    The "model" is a single confidence ``threshold`` — the review-grounded
    ``suggested_threshold`` at which precision meets ``target_precision`` (from the
    calibration report). When no threshold meets the target it falls back to ``1.0``
    (conservative: accept only near-certain). ``sample_count`` is the number of reviewed
    rows, so a well-reviewed node carries more weight in the aggregate.
    """
    cal = build_calibration_report(reviewed_rows, target_precision=target_precision)
    n = int(cal.get("reviewed", 0))
    st = cal.get("suggested_threshold")
    threshold = float(st) if st is not None else 1.0
    return {"node_id": node_id, "sample_count": n, "weights": {"threshold": [threshold]}}


def run_federated_round(
    updates: list[dict[str, Any]],
    trust: dict[str, float] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate ``updates`` into the next versioned global model.

    ``previous`` is the prior global model (or ``None`` for the first round); its
    ``version`` is incremented. Returns ``{version, weights, nodes, total_weight, params}``.
    """
    agg = federated_average(updates, trust=trust)
    version = (int(previous.get("version", 0)) + 1) if previous else 1
    return {
        "version": version,
        "weights": agg["weights"],
        "nodes": agg["nodes"],
        "total_weight": agg["total_weight"],
        "params": agg["params"],
    }


def federated_round_from_reviews(
    node_reviews: dict[str, list[dict[str, Any]]],
    target_precision: float = 0.9,
    trust: dict[str, float] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """End-to-end round: ``{node_id: reviewed_rows}`` → next global model.

    Builds each node's local update from its reviewed detections, then runs the round.
    """
    updates = [
        build_local_update(node_id, rows, target_precision=target_precision)
        for node_id, rows in node_reviews.items()
    ]
    return run_federated_round(updates, trust=trust, previous=previous)
