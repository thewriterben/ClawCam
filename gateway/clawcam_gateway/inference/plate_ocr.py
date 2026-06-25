"""License-plate OCR detector (driveway / outdoor-security profiles).

Refines a coarse MegaDetector ``vehicle`` hit into a vehicle whose ``species``
field carries the read license-plate string. It runs an OCR engine over the
frame, keeps plate-shaped tokens, and emits the highest-confidence one.

Design / offline-first
----------------------
The OCR engine (``easyocr``) is an optional, lazy dependency: ``is_available``
is ``False`` until ``easyocr`` imports, so the detector registry skips this
cleanly in CI and on gateways that haven't installed it. Install with::

    pip install "clawcam-gateway[ocr]"

``easyocr`` downloads its recognition models on first ``Reader`` construction,
so a field gateway needs that one-time fetch (or a pre-seeded model cache).

Accuracy note
-------------
This scaffold OCRs the whole frame and filters for plate-shaped tokens. A
production ALPR setup should first crop to the vehicle bounding box (e.g. from
the preceding MegaDetector result) before OCR; that refinement slots into
``detect`` without changing the contract or callers.
"""

from __future__ import annotations

import logging
import re

from clawcam_gateway.inference.detector import BaseDetector, Detection, InferenceResult

logger = logging.getLogger(__name__)

# Plate-shaped token: 4–8 chars, letters+digits only, containing at least one
# letter AND one digit (filters out plain words and pure numbers).
_PLATE_RE = re.compile(r"^[A-Z0-9]{4,8}$")


def looks_like_plate(text: str) -> bool:
    """Heuristic: does *text* look like a license plate after normalisation?"""
    t = normalise_plate(text)
    if not _PLATE_RE.match(t):
        return False
    return any(c.isalpha() for c in t) and any(c.isdigit() for c in t)


def normalise_plate(text: str) -> str:
    """Uppercase and strip everything except letters/digits."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


class PlateOCRDetector(BaseDetector):
    """OCR detector that emits a ``vehicle`` detection tagged with its plate."""

    def __init__(self, languages: tuple[str, ...] = ("en",), min_confidence: float = 0.40,
                 gpu: bool = False):
        self._languages = languages
        self._min_confidence = min_confidence
        self._gpu = gpu
        self._reader = None

    @property
    def model_name(self) -> str:
        return "plate_ocr"

    @property
    def model_version(self) -> str:
        return "0.1.0"

    @property
    def is_available(self) -> bool:
        try:
            import easyocr  # noqa: F401
        except Exception:  # noqa: BLE001 - any import problem => unavailable
            return False
        return True

    def _load(self) -> None:
        if self._reader is not None:
            return
        import easyocr

        # Reader construction triggers the one-time model download/cache.
        self._reader = easyocr.Reader(list(self._languages), gpu=self._gpu)

    def detect(self, image_path) -> InferenceResult:
        # Defensive: the orchestrator only calls available detectors, but never raise.
        if not self.is_available:
            return InferenceResult(self.model_name, self.model_version, [])

        self._load()
        assert self._reader is not None

        try:
            raw = self._reader.readtext(str(image_path))  # [(bbox, text, conf), ...]
        except Exception as exc:  # noqa: BLE001 - OCR errors must not abort the chain
            logger.warning("plate_ocr: readtext failed for %s: %s", image_path, exc)
            return InferenceResult(self.model_name, self.model_version, [])

        candidates = [
            (normalise_plate(text), float(conf))
            for (_bbox, text, conf) in raw
            if looks_like_plate(text) and float(conf) >= self._min_confidence
        ]
        if not candidates:
            # Vehicle may be present but no plate was read — record an empty result.
            return InferenceResult(self.model_name, self.model_version, [])

        plate, conf = max(candidates, key=lambda c: c[1])
        detection = Detection(
            label="vehicle",
            confidence=conf,
            bbox=[0.0, 0.0, 1.0, 1.0],
            species=plate,  # the read plate string rides in the species/identity slot
        )
        return InferenceResult(self.model_name, self.model_version, [detection])
