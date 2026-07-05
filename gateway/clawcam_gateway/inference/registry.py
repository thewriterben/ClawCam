"""Detector registry: maps detector names to factory callables.

Phase 12 lets a single device run *multiple* detectors per event — e.g.
a bird-feeder camera that runs both MegaDetector (animal vs background)
and a fine-grained bird classifier (species ID), or a home-security
camera that runs MegaDetector plus a face recognizer plus a license-plate
OCR. The registry is the indirection layer between profile defaults
("run [megadetector_v5, face_recognizer, plate_ocr]") and the actual
Python classes that implement each one.

Registration is module-level so new detector implementations can opt in
without modifying core code. Factories are called lazily — heavy models
(face_recognition, easyocr) only load when a device actually needs them.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

from clawcam_gateway.inference.detector import (
    BaseDetector,
    MockDetector,
)

logger = logging.getLogger(__name__)


# A factory is a zero-arg callable that returns a fresh detector instance.
DetectorFactory = Callable[[], BaseDetector]


class DetectorRegistry:
    """Name → factory mapping for detector lookup.

    A detector is "available" when its factory both succeeds and the
    returned instance reports ``is_available``. Names that aren't
    registered, or whose factory raises, or whose instance reports
    unavailable, are skipped silently by the orchestrator.
    """

    def __init__(self):
        self._factories: Dict[str, DetectorFactory] = {}
        self._instances: Dict[str, BaseDetector] = {}

    def register(self, name: str, factory: DetectorFactory) -> None:
        self._factories[name] = factory
        self._instances.pop(name, None)

    def resolve(self, name: str) -> BaseDetector | None:
        """Return a cached detector instance, or None if unavailable / unknown.

        Instances are cached per name: heavy models (YOLO weights, easyocr
        readers, face enrollments) load once per process instead of once per
        uploaded image. ``register`` and ``set_registry`` reset the cache.
        """
        cached = self._instances.get(name)
        if cached is not None:
            return cached if cached.is_available else None
        factory = self._factories.get(name)
        if factory is None:
            return None
        try:
            instance = factory()
        except Exception as exc:  # noqa: BLE001
            logger.debug("detector factory %r raised: %s", name, exc)
            return None
        if not instance.is_available:
            # Not cached: availability can change (weights installed later).
            return None
        self._instances[name] = instance
        return instance

    def names(self) -> list[str]:
        return list(self._factories.keys())

    def available_names(self) -> list[str]:
        return [n for n in self._factories if self.resolve(n) is not None]


# ── Default global registry ──────────────────────────────────────────────────


def _default_registry() -> DetectorRegistry:
    """Build the gateway's default registry.

    Heavy detectors are gated behind lazy imports inside the factory so
    importing this module doesn't trigger ultralytics / face_recognition
    / easyocr loading.
    """
    registry = DetectorRegistry()

    registry.register("mock_detector", lambda: MockDetector())

    def _megadetector():
        import os
        from pathlib import Path as _Path
        from clawcam_gateway.inference.detector import MegaDetectorV5
        weights_env = os.environ.get("CLAWCAM_INFERENCE_WEIGHTS")
        return MegaDetectorV5(weights_path=_Path(weights_env) if weights_env else None)

    registry.register("megadetector_v5", _megadetector)

    def _bird_classifier():
        # Real species classifier; lazy-loads torch + weights. Reports
        # unavailable (and is skipped) until a model is installed in models/.
        from clawcam_gateway.inference.bird_classifier import BirdClassifierDetector
        return BirdClassifierDetector()
    registry.register("bird_classifier", _bird_classifier)

    def _face_recognizer():
        # Real face detection/recognition; lazy-loads face_recognition (dlib).
        from clawcam_gateway.inference.face_recognizer import FaceRecognizerDetector
        return FaceRecognizerDetector()
    registry.register("face_recognizer", _face_recognizer)

    def _plate_ocr():
        # Real OCR detector; lazy-loads easyocr. Skipped until installed.
        from clawcam_gateway.inference.plate_ocr import PlateOCRDetector
        return PlateOCRDetector()
    registry.register("plate_ocr", _plate_ocr)

    # Audio classifier names are registered so profile chains may mention
    # them, but they resolve as unavailable in the *visual* orchestrator:
    # audio is scored by the audio pipeline (Phase 11), and the previous
    # MockDetector placeholders fabricated visual detections from thin air.
    def _audio_birdnet():
        raise NotImplementedError(
            "audio_birdnet is handled by the audio pipeline, not the visual orchestrator"
        )
    registry.register("audio_birdnet", _audio_birdnet)

    def _audio_glassbreak():
        raise NotImplementedError(
            "audio_glassbreak is handled by the audio pipeline, not the visual orchestrator"
        )
    registry.register("audio_glassbreak", _audio_glassbreak)

    return registry


_REGISTRY = _default_registry()


def get_registry() -> DetectorRegistry:
    """Return the global default registry. Tests can replace it via ``set_registry``."""
    return _REGISTRY


def set_registry(registry: DetectorRegistry) -> None:  # for tests
    global _REGISTRY
    _REGISTRY = registry
