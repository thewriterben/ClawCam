"""Face detection + recognition detector (home-security profiles).

Refines a coarse MegaDetector ``person`` hit by locating faces in the frame and,
when an enrolled match is found, tagging the ``person`` detection's ``species``
field with the recognised name (otherwise ``"unknown"``).

Design / offline-first
----------------------
The recognition engine (``face_recognition``, dlib-based) is an optional, lazy
dependency: ``is_available`` is ``False`` until it imports, so the registry skips
this detector in CI and on gateways that haven't installed it. Install with::

    pip install "clawcam-gateway[faces]"

Enrolled identities are loaded from ``<models_dir>/known_faces/<name>.jpg`` (the
filename stem is the person's name). With no enrollment directory, faces are
still detected but always reported as ``"unknown"`` — useful as a "face present,
unidentified" signal. Encodings are computed locally; no image leaves the device.

Privacy
-------
Facial recognition is biometric processing. Pair it with ``privacy_mask`` zones
(Phase 10) for areas that should never be analysed, and confirm it is lawful for
the deployment before enabling. This is why the home-security profiles flag
``privacy_zones_strongly_recommended``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from clawcam_gateway.inference.detector import BaseDetector, Detection, InferenceResult

logger = logging.getLogger(__name__)

DEFAULT_MODELS_DIR = Path(os.getenv("CLAWCAM_MODELS_DIR", "models"))
DEFAULT_KNOWN_FACES_DIRNAME = "known_faces"
UNKNOWN = "unknown"


def normalise_face_box(location: tuple[int, int, int, int], width: int, height: int) -> list[float]:
    """Convert a face_recognition (top, right, bottom, left) box in pixels to
    a normalised [x1, y1, x2, y2] in 0–1."""
    top, right, bottom, left = location
    w = float(width) or 1.0
    h = float(height) or 1.0
    clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
    return [clamp(left / w), clamp(top / h), clamp(right / w), clamp(bottom / h)]


class FaceRecognizerDetector(BaseDetector):
    """Emits a ``person`` detection per face, tagged with a recognised name."""

    def __init__(self, known_faces_dir: str | Path | None = None, tolerance: float = 0.6):
        self._known_faces_dir = (
            Path(known_faces_dir) if known_faces_dir
            else DEFAULT_MODELS_DIR / DEFAULT_KNOWN_FACES_DIRNAME
        )
        self._tolerance = tolerance
        self._known_encodings: list = []
        self._known_names: list[str] = []
        self._loaded = False

    @property
    def model_name(self) -> str:
        return "face_recognizer"

    @property
    def model_version(self) -> str:
        return "0.1.0"

    @property
    def is_available(self) -> bool:
        try:
            import face_recognition  # noqa: F401
        except Exception:  # noqa: BLE001 - any import problem => unavailable
            return False
        return True

    def _load_known_faces(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._known_faces_dir.is_dir():
            return
        import face_recognition

        for img_path in sorted(self._known_faces_dir.glob("*")):
            if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            try:
                image = face_recognition.load_image_file(str(img_path))
                encs = face_recognition.face_encodings(image)
            except Exception as exc:  # noqa: BLE001
                logger.warning("face_recognizer: could not enroll %s: %s", img_path, exc)
                continue
            if encs:
                self._known_encodings.append(encs[0])
                self._known_names.append(img_path.stem)

    def _match(self, encoding) -> tuple[str, float]:
        """Return (name, confidence). name is UNKNOWN when no enrolled match."""
        if not self._known_encodings:
            return UNKNOWN, 0.6  # face present, no enrollment to match against
        import face_recognition

        distances = face_recognition.face_distance(self._known_encodings, encoding)
        best_idx = min(range(len(distances)), key=lambda i: distances[i])
        best = float(distances[best_idx])
        if best <= self._tolerance:
            return self._known_names[best_idx], max(0.0, min(1.0, 1.0 - best))
        return UNKNOWN, 0.6

    def detect(self, image_path) -> InferenceResult:
        if not self.is_available:
            return InferenceResult(self.model_name, self.model_version, [])

        import face_recognition

        self._load_known_faces()
        try:
            image = face_recognition.load_image_file(str(image_path))
            locations = face_recognition.face_locations(image)
        except Exception as exc:  # noqa: BLE001 - never abort the chain
            logger.warning("face_recognizer: failed on %s: %s", image_path, exc)
            return InferenceResult(self.model_name, self.model_version, [])

        if not locations:
            return InferenceResult(self.model_name, self.model_version, [])

        height, width = image.shape[0], image.shape[1]
        encodings = face_recognition.face_encodings(image, locations)
        detections: list[Detection] = []
        for enc, loc in zip(encodings, locations):
            name, conf = self._match(enc)
            detections.append(
                Detection(
                    label="person",
                    confidence=conf,
                    bbox=normalise_face_box(loc, width, height),
                    species=name,
                )
            )
        return InferenceResult(self.model_name, self.model_version, detections)
