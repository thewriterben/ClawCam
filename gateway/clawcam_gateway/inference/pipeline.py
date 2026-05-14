"""Inference pipeline — runs a detector on an image and persists results.

Designed to be called synchronously from the gateway event ingest path.
The heavy lifting (model load) happens once; subsequent calls reuse the
loaded model. If inference fails for any reason, the error is logged and
the ingest path continues — a missing inference result never blocks event
storage.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .detector import BaseDetector, InferenceResult, get_detector

log = logging.getLogger(__name__)


class InferencePipeline:
    """Stateful pipeline that holds a loaded detector and a database handle.

    Parameters
    ----------
    db:
        A ``Database`` instance (from ``clawcam_gateway.storage.database``).
        Passed as Any to avoid a circular import; duck-typed at runtime.
    detector:
        Optional pre-built detector. If None, ``get_detector()`` picks the
        best available model (real weights > mock).
    enabled:
        When False the pipeline short-circuits without running inference.
        Set via config or env so tests can disable it without mocking.
    """

    def __init__(self, db, detector: Optional[BaseDetector] = None, enabled: bool = True):
        self._db = db
        self._detector = detector
        self._enabled = enabled

    def _get_detector(self) -> BaseDetector:
        if self._detector is None:
            self._detector = get_detector()
            log.info("inference: using detector %s %s",
                     self._detector.model_name, self._detector.model_version)
        return self._detector

    def run(self, event_id: str, media_path: str) -> Optional[InferenceResult]:
        """Run inference for a given event and persist the result.

        Returns the InferenceResult on success, None if skipped or failed.
        Never raises — inference errors are non-fatal.
        """
        if not self._enabled:
            return None

        path = Path(media_path)
        if not path.exists():
            log.warning("inference: media file not found: %s", media_path)
            return None

        suffix = path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            log.debug("inference: skipping non-image file %s", media_path)
            return None

        try:
            detector = self._get_detector()
            result = detector.detect(path)
            self._db.save_inference_result(event_id, media_path, result)
            log.info(
                "inference: event=%s label=%s confidence=%.3f species=%s model=%s",
                event_id,
                result.top_label or "empty",
                result.top_confidence,
                result.top_species or "none",
                result.model_name,
            )
            return result
        except Exception as exc:
            log.error("inference: failed for event %s: %s", event_id, exc)
            return None
