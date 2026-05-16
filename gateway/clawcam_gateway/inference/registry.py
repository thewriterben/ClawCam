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

    def register(self, name: str, factory: DetectorFactory) -> None:
        self._factories[name] = factory

    def resolve(self, name: str) -> BaseDetector | None:
        """Return a fresh detector instance, or None if unavailable / unknown."""
        factory = self._factories.get(name)
        if factory is None:
            return None
        try:
            instance = factory()
        except Exception as exc:  # noqa: BLE001
            logger.debug("detector factory %r raised: %s", name, exc)
            return None
        if not instance.is_available:
            return None
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
        from clawcam_gateway.inference.detector import MegaDetectorV5
        return MegaDetectorV5()

    registry.register("megadetector_v5", _megadetector)

    def _bird_classifier():
        # Placeholder — bird-feeder profile asks for this; for now we
        # alias to MockDetector with a label biased to "bird" so the
        # orchestrator wires through cleanly. Real implementation slots
        # in here without touching callers.
        return MockDetector()
    registry.register("bird_classifier", _bird_classifier)

    def _face_recognizer():
        return MockDetector()  # placeholder
    registry.register("face_recognizer", _face_recognizer)

    def _plate_ocr():
        return MockDetector()  # placeholder
    registry.register("plate_ocr", _plate_ocr)

    # Audio classifiers also opt in here so the orchestrator can chain
    # them across modalities in a future phase.
    def _audio_birdnet():
        return MockDetector()  # placeholder visual no-op
    registry.register("audio_birdnet", _audio_birdnet)

    def _audio_glassbreak():
        return MockDetector()
    registry.register("audio_glassbreak", _audio_glassbreak)

    return registry


_REGISTRY = _default_registry()


def get_registry() -> DetectorRegistry:
    """Return the global default registry. Tests can replace it via ``set_registry``."""
    return _REGISTRY


def set_registry(registry: DetectorRegistry) -> None:  # for tests
    global _REGISTRY
    _REGISTRY = registry
