"""Federated learning primitives for ClawCam (Conservation Grid G9).

Camera nodes improve their detectors from *local* human-review labels without shipping raw
imagery off-site. This package holds the aggregation core — FedAvg — that combines those
per-node model updates into a shared global model.
"""

from clawcam_gateway.federated.fedavg import federated_average
from clawcam_gateway.federated.round import (
    build_local_update,
    federated_round_from_reviews,
    run_federated_round,
)

__all__ = [
    "federated_average",
    "build_local_update",
    "run_federated_round",
    "federated_round_from_reviews",
]
