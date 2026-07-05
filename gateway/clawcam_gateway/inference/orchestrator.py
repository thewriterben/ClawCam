"""InferenceOrchestrator: runs a chain of detectors per device profile.

Resolves the detector list in priority order:

  1. Device-level ``detector_chain_json`` column (per-device override),
  2. Profile defaults (``ProfileDefaults.default_detectors``),
  3. ``["megadetector_v5"]`` as the fallback (mock_detector never enters
     a chain implicitly — it fabricates detections).

Each resolvable detector runs against the same image; its result is
persisted as a separate ``inference_results`` row. When two or more
detectors store results, their outputs are **fused** (``boxops.merge_results``)
into one consolidated row stored with ``role='fused'``, and the raw
per-detector rows are demoted to ``role='chain_member'`` — replace, not
add, so analytics and the review queue count each subject once. The
fused row is what ``get_inference_result`` returns, so alert rules see
the enriched (species-carrying, deduplicated) result.

Per-detector failures log and skip — one broken detector never blocks
the rest of the chain; a fusion failure never blocks the chain rows.
"""

from __future__ import annotations

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

    def __init__(self, db: "GatewayDatabase", enabled: bool = True, registry=None):
        self._db = db
        self._enabled = enabled
        self._registry = registry if registry is not None else get_registry()

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
        return list(defaults.default_detectors) or ["megadetector_v5"]

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

        from clawcam_gateway.config import mocks_allowed

        from clawcam_gateway.inference.boxops import merge_results
        from clawcam_gateway.storage.database import RESULT_ROLE_FUSED

        chain = self.chain_for_device(device_id) if device_id else ["megadetector_v5"]
        # Demo/CI fallback: when mocks are explicitly allowed and the chain
        # has no mock in it, append one so a model-less gateway still
        # produces deterministic detections. Production (flag unset) instead
        # skips unavailable detectors and records nothing.
        if mocks_allowed() and "mock_detector" not in chain:
            chain = [*chain, "mock_detector"]
        summaries: list[dict[str, Any]] = []
        stored: list[tuple[str, int, Any]] = []  # (detector, result_id, result)

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
                result_id = self._db.save_inference_result(event_id, str(image_path), result)
                stored.append((name, result_id, result))
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

        # Chain fusion (replace-not-add): with 2+ stored results, persist one
        # consolidated fused row and demote the raw rows to chain members so
        # default listings count each subject once. Members are preserved as
        # field evidence (visible via the per-event chain view). A single
        # stored result stays 'single' — nothing to fuse.
        if len(stored) >= 2:
            try:
                fused = merge_results([r for _, _, r in stored])
                self._db.save_inference_result(
                    event_id, str(image_path), fused, role=RESULT_ROLE_FUSED,
                )
                self._db.demote_to_chain_members([rid for _, rid, _ in stored])
                summaries.append({
                    "detector": "fused",
                    "stored": True,
                    "top_label": fused.top_label,
                    "top_confidence": fused.top_confidence,
                    "top_species": fused.top_species,
                    "members": [n for n, _, _ in stored],
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("orchestrator: fusion failed for %s: %s", event_id, exc)
                summaries.append({"detector": "fused", "stored": False,
                                   "reason": f"fusion failed: {exc}"})

        return summaries
