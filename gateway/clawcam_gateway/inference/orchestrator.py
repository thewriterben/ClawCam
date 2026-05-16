"""InferenceOrchestrator: runs a chain of detectors per device profile.

Resolves the detector list in priority order:

  1. Device-level ``detector_chain_json`` column (per-device override),
  2. Profile defaults (``ProfileDefaults.default_detectors``),
  3. ``["mock_detector"]`` as the always-works fallback.

Each resolvable detector runs against the same image; its result is
persisted as a separate ``inference_results`` row. The first
detector's result is also returned by the legacy
``get_inference_result`` view so existing alert rules and queries keep
working without changes.

Per-detector failures log and skip — one broken detector never blocks
the rest of the chain.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clawcam_gateway.inference.registry import get_registry
from clawcam_gateway.profiles import (
    DEFAULT_PROFILE,
    get_profile_defaults,
)

if TYPE_CHECKING:
    from clawcam_gateway.storage.database import GatewayDatabase

logger = logging.getLogger(__name__)


class InferenceOrchestrator:
    """Picks the detector chain for a device and runs every available one."""

    def __init__(self, db: "GatewayDatabase", enabled: bool = True):
        self._db = db
        self._enabled = enabled
        self._registry = get_registry()

    # ── Chain resolution ──────────────────────────────────────────────────

    def chain_for_device(self, device_id: str) -> list[str]:
        """Resolve the ordered detector chain for *device_id*."""
        device = self._db.get_device(device_id) if device_id else None
        # Per-device override (stored as JSON array of detector names)
        if device:
            raw_override = device.get("detector_chain")
            if isinstance(raw_override, list) and raw_override:
                return [str(n) for n in raw_override]
            # Or from the profile attached to the device row
            profile = device.get("profile") or DEFAULT_PROFILE
        else:
            profile = DEFAULT_PROFILE
        defaults = get_profile_defaults(profile)
        return list(defaults.default_detectors) or ["mock_detector"]

    # ── Per-event run ─────────────────────────────────────────────────────

    def run(self, event_id: str, image_path: str | Path,
            device_id: str | None = None) -> list[dict[str, Any]]:
        """Run every available detector in the chain. Persist each result.

        Returns one summary dict per detector that actually ran::

            [{"detector": "megadetector_v5", "stored": True,
              "top_label": "animal", "top_confidence": 0.92}, ...]
        """
        if not self._enabled:
            return []

        chain = self.chain_for_device(device_id) if device_id else ["mock_detector"]
        summaries: list[dict[str, Any]] = []

        for name in chain:
            detector = self._registry.resolve(name)
            if detector is None:
                logger.debug("orchestrator: detector %r unavailable, skipping", name)
                summaries.append({"detector": name, "stored": False,
                                   "reason": "unavailable"})
                continue
            try:
                result = detector.detect(Path(image_path))
            except Exception as exc:  # noqa: BLE001
                logger.warning("orchestrator: detector %r raised: %s", name, exc)
                summaries.append({"detector": name, "stored": False,
                                   "reason": f"raised: {exc}"})
                continue
            try:
                self._db.save_inference_result(event_id, str(image_path), result)
                summaries.append({
                    "detector": name,
                    "stored": True,
                    "top_label": result.top_label,
                    "top_confidence": result.top_confidence,
                    "top_species": result.top_species,
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("orchestrator: store failed for %r: %s", name, exc)
                summaries.append({"detector": name, "stored": False,
                                   "reason": f"store failed: {exc}"})

        return summaries
