"""Deterministic multi-day detection streams for exercising the analytics suite.

The node simulator ([`node_simulator`]) emits one schema-complete capture at a time —
ideal for import/schema tests. This module is the complement: a seeded generator that
produces a *realistic stream* of detection rows spanning many days, with per-species diel
activity (nocturnal / diurnal / crepuscular / cathemeral) and configurable daily rates,
plus optional injected **spike** and **drop** days. The rows carry exactly the fields the
analytics builders read (``top_species`` / ``top_label`` / ``top_confidence`` / ``ran_at``
/ ``review_state``), so a stream feeds straight into ``build_activity_report``,
``build_anomaly_report``, ``build_encounter_report``, etc.

Pure and deterministic: given the same ``seed`` it always yields the same stream, so it
doubles as a test fixture and a demo data source. No database, no I/O.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# 24-hour activity weights per diel pattern (index = hour of day, UTC).
_NIGHT = [3, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 3, 3, 3, 3]
_DAY = [1, 1, 1, 1, 1, 1, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1]
_CREP = [1, 1, 1, 1, 1, 2, 3, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1, 2, 3, 3, 2, 1, 1, 1]
_FLAT = [1] * 24

_DIEL_WEIGHTS = {
    "nocturnal": _NIGHT,
    "diurnal": _DAY,
    "crepuscular": _CREP,
    "cathemeral": _FLAT,
}


@dataclass(frozen=True)
class SpeciesProfile:
    """A species' presence in the stream."""

    name: str                     # e.g. "white-tailed deer" → top_species
    label: str = "animal"         # coarse detector label → top_label
    daily_rate: float = 5.0       # mean detections per normal day
    diel: str = "cathemeral"      # activity pattern (see _DIEL_WEIGHTS)
    confidence_mean: float = 0.85
    confidence_sd: float = 0.08


@dataclass(frozen=True)
class ScenarioSpec:
    """A full scenario: which species, how many days, and which days are unusual."""

    species: list[SpeciesProfile]
    days: int = 7
    start_date: str = "2026-05-01"        # first day (UTC), YYYY-MM-DD
    device_id: str = "node-001"
    deployment_id: str = "deploy-north-ridge-2026"
    seed: int = 0
    spike_days: list[int] = field(default_factory=list)   # 0-based day indices, ~5x rate
    drop_days: list[int] = field(default_factory=list)    # 0-based day indices, ~0 rate
    spike_multiplier: float = 5.0


def _sample_hour(rng: random.Random, diel: str) -> int:
    weights = _DIEL_WEIGHTS.get(diel, _FLAT)
    return rng.choices(range(24), weights=weights, k=1)[0]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def build_detection_stream(spec: ScenarioSpec) -> list[dict[str, Any]]:
    """Generate a deterministic list of detection rows for a scenario.

    Each row is ``{event_id, device_id, deployment_id, top_label, top_species,
    top_confidence, ran_at, review_state}`` — the analytics-input shape. Rows are returned
    in ascending ``ran_at`` order. Determined entirely by ``spec.seed``.
    """
    rng = random.Random(spec.seed)
    base = datetime.strptime(spec.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    spikes = set(spec.spike_days)
    drops = set(spec.drop_days)

    rows: list[dict[str, Any]] = []
    for day in range(max(0, spec.days)):
        day_start = base + timedelta(days=day)
        for sp in spec.species:
            rate = sp.daily_rate
            if day in drops:
                rate = 0.0
            elif day in spikes:
                rate *= spec.spike_multiplier
            # Poisson-like count via the mean; deterministic through the seeded rng.
            count = _poisson(rng, rate)
            for _ in range(count):
                hour = _sample_hour(rng, sp.diel)
                minute = rng.randint(0, 59)
                second = rng.randint(0, 59)
                ts = day_start + timedelta(hours=hour, minutes=minute, seconds=second)
                conf = _clamp(rng.gauss(sp.confidence_mean, sp.confidence_sd), 0.05, 0.999)
                rows.append({
                    "event_id": f"evt-{uuid.UUID(int=rng.getrandbits(128)).hex[:12]}",
                    "device_id": spec.device_id,
                    "deployment_id": spec.deployment_id,
                    "top_label": sp.label,
                    "top_species": sp.name,
                    "top_confidence": round(conf, 4),
                    "ran_at": ts.isoformat(),
                    "review_state": "unreviewed",
                })

    rows.sort(key=lambda r: r["ran_at"])
    return rows


def _poisson(rng: random.Random, mean: float) -> int:
    """Knuth's algorithm — a Poisson draw from the seeded rng. Small means only."""
    if mean <= 0.0:
        return 0
    import math

    limit = math.exp(-mean)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= limit:
            return k - 1
