"""Persist a scenario detection stream into a gateway database.

[`build_detection_stream`][clawcam_gateway.simulator.scenario] yields pure,
analytics-shaped rows. This module writes such a stream into a real database so
the live tools, REST endpoints, and dashboard show *realistic historic data*
without a camera or a running node — the missing bridge between the deterministic
generator and the storage-backed analytics.

For each row it upserts the device once, inserts one capture ``event`` (so the
event/media views and the ``inference_results`` foreign key stay coherent), and
saves one ``inference_results`` row **backdated to the row's ``ran_at``** (see
``ClawcamDatabase.save_inference_result``'s ``ran_at`` parameter). Optionally it
deterministically labels a fraction of rows with human-review states so the
calibration and review-queue tools have ground truth to work with.

The database is duck-typed — anything exposing ``upsert_device``, ``add_event``,
``save_inference_result(event_id, media_path, result, ran_at=…)`` and
``set_review_state`` works — so the loader is unit-testable against a fake.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class _ScenarioResult:
    """Duck-typed InferenceResult for ``save_inference_result``."""

    row: dict[str, Any]
    model_name: str
    model_version: str

    def to_dict(self) -> dict[str, Any]:
        label = self.row.get("top_label")
        species = self.row.get("top_species")
        conf = float(self.row.get("top_confidence") or 0.0)
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "detections": [
                {"label": label, "confidence": conf, "species": species,
                 "bbox": [0.4, 0.4, 0.6, 0.6]}
            ],
            "top_label": label,
            "top_confidence": conf,
            "top_species": species,
            "review_state": "unreviewed",
        }


def load_stream_into_db(
    db: Any,
    stream: list[dict[str, Any]],
    *,
    model_name: str = "scenario-sim",
    model_version: str = "1.0.0",
    device_name: str = "Scenario Simulator",
    reviewed_frac: float = 0.0,
    review_seed: int = 0,
) -> dict[str, int]:
    """Persist a detection ``stream`` into ``db``. Returns counts.

    Args:
        db:             A gateway database (duck-typed, see module docstring).
        stream:         Rows from ``build_detection_stream``.
        model_name/version: Recorded on every inference row.
        device_name:    Display name for the upserted simulated device(s).
        reviewed_frac:  Fraction (``0..1``) of rows to assign a human-review
                        state. A reviewed row is ``verified`` with probability
                        equal to its confidence, else ``rejected`` — so higher
                        confidence really does mean more likely correct, giving
                        the calibration report a meaningful signal.
        review_seed:    Seed for the deterministic review-labeling draw.

    Returns a dict with ``devices``, ``events``, ``results`` and ``reviewed``.
    """
    rng = random.Random(review_seed)
    frac = max(0.0, min(1.0, reviewed_frac))
    seen_devices: set[str] = set()
    counts = {"devices": 0, "events": 0, "results": 0, "reviewed": 0}

    for row in stream:
        device_id = row["device_id"]
        deployment_id = row["deployment_id"]
        ran_at = row["ran_at"]

        if device_id not in seen_devices:
            db.upsert_device({
                "device_id": device_id,
                "device_type": "camera-node",
                "name": device_name,
                "status": "online",
                "created_at": ran_at,
                "last_seen_at": ran_at,
                "deployment_id": deployment_id,
            })
            seen_devices.add(device_id)
            counts["devices"] += 1

        event_id = row["event_id"]
        db.add_event({
            "event_id": event_id,
            "event_type": "detection",
            "device_id": device_id,
            "timestamp": ran_at,
            "source": "scenario-sim",
            "deployment_id": deployment_id,
            "media": [],
        })
        counts["events"] += 1

        result = _ScenarioResult(row, model_name, model_version)
        result_id = db.save_inference_result(
            event_id, f"sim://{event_id}.jpg", result, ran_at=ran_at
        )
        counts["results"] += 1

        # Deterministically label a fraction as reviewed for calibration ground truth.
        if frac > 0.0 and rng.random() < frac:
            conf = float(row.get("top_confidence") or 0.0)
            state = "verified" if rng.random() < conf else "rejected"
            db.set_review_state(result_id, state, reviewer="scenario-sim")
            counts["reviewed"] += 1

    return counts
