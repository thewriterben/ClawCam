"""Tests for the PlateOCRDetector scaffold.

easyocr isn't installed in CI, so these cover the plate heuristic, availability
gating, registry wiring, and graceful skip. The OCR path activates only when
easyocr is installed (pip install "clawcam-gateway[ocr]") and is exercised in
the field / hardware test.
"""

from __future__ import annotations

from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.inference.orchestrator import InferenceOrchestrator
from clawcam_gateway.inference.plate_ocr import (
    PlateOCRDetector,
    looks_like_plate,
    normalise_plate,
)
from clawcam_gateway.inference.registry import DetectorRegistry, get_registry
from clawcam_gateway.storage.database import GatewayDatabase


def test_metadata():
    det = PlateOCRDetector()
    assert det.model_name == "plate_ocr"
    assert det.model_version == "0.1.0"


def test_normalise_plate():
    assert normalise_plate("7ab c-123") == "7ABC123"
    assert normalise_plate(None) == ""


def test_looks_like_plate():
    assert looks_like_plate("ABC123")
    assert looks_like_plate("7-ABC-12")
    assert not looks_like_plate("HELLO")      # letters only
    assert not looks_like_plate("12345")      # digits only
    assert not looks_like_plate("AB")         # too short
    assert not looks_like_plate("ABCDEFGHIJ") # too long


def test_unavailable_without_easyocr():
    # easyocr is not installed in CI -> detector reports unavailable.
    assert PlateOCRDetector().is_available is False


def test_detect_safe_when_unavailable(tmp_path):
    det = PlateOCRDetector()
    result = det.detect(tmp_path / "frame.jpg")
    assert isinstance(result, InferenceResult)
    assert result.detections == []


def test_registered_in_default_registry():
    assert "plate_ocr" in get_registry().names()


def test_orchestrator_skips_unavailable_plate_ocr(tmp_path):
    db = GatewayDatabase(tmp_path / "g.db")
    db.add_event({
        "event_id": "evt-po", "event_type": "capture", "device_id": "cam-po",
        "timestamp": "2026-05-12T00:00:00Z", "source": "node", "media": [],
    })
    img = tmp_path / "x.jpg"
    img.write_bytes(b"FAKEJPEG")
    db.set_device_detector_chain("cam-po", ["mock_detector", "plate_ocr"])
    orch = InferenceOrchestrator(db=db)
    stored = [s for s in orch.run("evt-po", str(img), device_id="cam-po") if s.get("stored")]
    assert any(s["detector"] == "mock_detector" for s in stored)
    assert all(s["detector"] != "plate_ocr" for s in stored)


def test_registry_resolves_when_available():
    reg = DetectorRegistry()
    reg.register("plate_ocr", lambda: _AlwaysAvailablePlate())
    assert reg.resolve("plate_ocr") is not None
    assert "plate_ocr" in reg.available_names()


class _AlwaysAvailablePlate(PlateOCRDetector):
    @property
    def is_available(self) -> bool:
        return True

    def detect(self, image_path):
        return InferenceResult(self.model_name, self.model_version,
                               [Detection(label="vehicle", confidence=0.88,
                                          bbox=[0.0, 0.0, 1.0, 1.0], species="7ABC123")])
