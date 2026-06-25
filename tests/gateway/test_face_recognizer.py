"""Tests for the FaceRecognizerDetector scaffold.

face_recognition isn't installed in CI, so these cover the box-normalisation
helper, availability gating, registry wiring, and graceful skip. The recognition
path activates only when face_recognition is installed
(pip install "clawcam-gateway[faces]") and is exercised in the field test.
"""

from __future__ import annotations

from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.inference.face_recognizer import (
    UNKNOWN,
    FaceRecognizerDetector,
    normalise_face_box,
)
from clawcam_gateway.inference.orchestrator import InferenceOrchestrator
from clawcam_gateway.inference.registry import DetectorRegistry, get_registry
from clawcam_gateway.storage.database import GatewayDatabase


def test_metadata():
    det = FaceRecognizerDetector()
    assert det.model_name == "face_recognizer"
    assert det.model_version == "0.1.0"


def test_normalise_face_box():
    # (top, right, bottom, left) in a 200x100 (w x h) frame
    box = normalise_face_box((10, 150, 60, 50), width=200, height=100)
    assert box == [0.25, 0.1, 0.75, 0.6]
    # out-of-range pixels are clamped to [0, 1]
    assert normalise_face_box((-5, 500, 500, -5), 200, 100) == [0.0, 0.0, 1.0, 1.0]


def test_unavailable_without_face_recognition():
    assert FaceRecognizerDetector().is_available is False


def test_detect_safe_when_unavailable(tmp_path):
    det = FaceRecognizerDetector(known_faces_dir=tmp_path / "none")
    result = det.detect(tmp_path / "frame.jpg")
    assert isinstance(result, InferenceResult)
    assert result.detections == []


def test_registered_in_default_registry():
    assert "face_recognizer" in get_registry().names()


def test_orchestrator_skips_unavailable_face_recognizer(tmp_path):
    db = GatewayDatabase(tmp_path / "g.db")
    db.add_event({
        "event_id": "evt-fr", "event_type": "capture", "device_id": "cam-fr",
        "timestamp": "2026-05-12T00:00:00Z", "source": "node", "media": [],
    })
    img = tmp_path / "x.jpg"
    img.write_bytes(b"FAKEJPEG")
    db.set_device_detector_chain("cam-fr", ["mock_detector", "face_recognizer"])
    orch = InferenceOrchestrator(db=db)
    stored = [s for s in orch.run("evt-fr", str(img), device_id="cam-fr") if s.get("stored")]
    assert any(s["detector"] == "mock_detector" for s in stored)
    assert all(s["detector"] != "face_recognizer" for s in stored)


def test_registry_resolves_when_available():
    reg = DetectorRegistry()
    reg.register("face_recognizer", lambda: _AlwaysAvailableFace())
    assert reg.resolve("face_recognizer") is not None
    assert "face_recognizer" in reg.available_names()


class _AlwaysAvailableFace(FaceRecognizerDetector):
    @property
    def is_available(self) -> bool:
        return True

    def detect(self, image_path):
        return InferenceResult(self.model_name, self.model_version,
                               [Detection(label="person", confidence=0.82,
                                          bbox=[0.2, 0.1, 0.4, 0.5], species=UNKNOWN)])
