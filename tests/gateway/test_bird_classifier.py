"""Tests for the BirdClassifierDetector scaffold.

The real model + weights aren't present in CI, so these verify the
availability gating, registry wiring, and graceful-skip behaviour. The actual
inference path activates only when a TorchScript model is installed in models/
(see models/README.md) and is exercised in the field / hardware test.
"""

from __future__ import annotations

from clawcam_gateway.inference.bird_classifier import BirdClassifierDetector
from clawcam_gateway.inference.detector import InferenceResult, MockDetector
from clawcam_gateway.inference.orchestrator import InferenceOrchestrator
from clawcam_gateway.inference.registry import DetectorRegistry, get_registry
from clawcam_gateway.storage.database import GatewayDatabase


def test_metadata():
    det = BirdClassifierDetector()
    assert det.model_name == "bird_classifier"
    assert det.model_version == "0.1.0"


def test_unavailable_without_weights(tmp_path):
    # Point at non-existent weights -> not available, regardless of torch.
    det = BirdClassifierDetector(
        weights_path=tmp_path / "missing.pt",
        labels_path=tmp_path / "missing.txt",
    )
    assert det.is_available is False


def test_detect_is_safe_when_unavailable(tmp_path):
    """detect() must never raise even if called while unavailable."""
    det = BirdClassifierDetector(
        weights_path=tmp_path / "missing.pt",
        labels_path=tmp_path / "missing.txt",
    )
    result = det.detect(tmp_path / "whatever.jpg")
    assert isinstance(result, InferenceResult)
    assert result.detections == []


def test_registered_in_default_registry():
    assert "bird_classifier" in get_registry().names()


def test_orchestrator_skips_unavailable_bird_classifier(tmp_path):
    """A chain entry that is registered but unavailable is skipped cleanly."""
    db = GatewayDatabase(tmp_path / "g.db")
    db.add_event({
        "event_id": "evt-bc", "event_type": "capture", "device_id": "cam-bc",
        "timestamp": "2026-05-12T00:00:00Z", "source": "node", "media": [],
    })
    img = tmp_path / "x.jpg"
    img.write_bytes(b"FAKEJPEG")
    db.set_device_detector_chain("cam-bc", ["mock_detector", "bird_classifier"])
    orch = InferenceOrchestrator(db=db)  # default registry: bird_classifier unavailable in CI
    summaries = orch.run("evt-bc", str(img), device_id="cam-bc")
    stored = [s for s in summaries if s.get("stored")]
    # mock_detector stored; bird_classifier skipped (no weights installed).
    assert any(s["detector"] == "mock_detector" for s in stored)
    assert all(s["detector"] != "bird_classifier" for s in stored)


def test_registry_resolves_real_class_when_available(monkeypatch, tmp_path):
    """When weights exist and the class reports available, the registry resolves it."""
    # A stand-in that mimics an installed model by reporting available.
    reg = DetectorRegistry()
    reg.register("bird_classifier", lambda: _AlwaysAvailableBird())
    assert reg.resolve("bird_classifier") is not None
    assert "bird_classifier" in reg.available_names()


class _AlwaysAvailableBird(BirdClassifierDetector):
    @property
    def is_available(self) -> bool:
        return True

    def detect(self, image_path):
        from clawcam_gateway.inference.detector import Detection
        return InferenceResult(self.model_name, self.model_version,
                               [Detection(label="animal", confidence=0.91,
                                          bbox=[0.0, 0.0, 1.0, 1.0],
                                          species="American Robin")])
