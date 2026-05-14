"""Phase 3 tests — AI inference pipeline, detector abstraction, and inference tools."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import (
    Detection,
    InferenceResult,
    MockDetector,
    MegaDetectorV5,
    get_detector,
)
from clawcam_gateway.inference.pipeline import InferencePipeline
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import ToolContext, get_inference_results, list_species_detections


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path) -> GatewayDatabase:
    return GatewayDatabase(tmp_path / "test.db")


@pytest.fixture()
def app_and_db(tmp_path):
    config = GatewayConfig(
        database_path=tmp_path / "test.db",
        media_dir=tmp_path / "media",
        inference_enabled=True,
    )
    app = create_app(config)
    db = GatewayDatabase(config.database_path)
    return TestClient(app), db, config


@pytest.fixture()
def registered_device_with_event(app_and_db):
    """Register a device and ingest one event; return (client, db, config, device_id, event_id)."""
    client, db, config = app_and_db
    device_id = "node-inference-001"
    event_id = "evt-inference-001"

    client.post("/api/v1/devices", json={"data": {
        "device_id": device_id,
        "device_type": "node",
        "name": "Inference Test Node",
        "status": "active",
        "capabilities": ["cap_clawcam_camera_trap"],
        "created_at": "2026-05-13T00:00:00Z",
        "last_seen_at": "2026-05-13T00:00:00Z",
    }})
    client.post("/api/v1/events", json={"data": {
        "event_id": event_id,
        "event_type": "capture",
        "device_id": device_id,
        "timestamp": "2026-05-13T06:00:00Z",
        "time_source": "rtc",
        "source": "node",
        "trigger": "pir_motion",
        "media": [],
    }})
    return client, db, config, device_id, event_id


# ── InferenceResult data model ────────────────────────────────────────────────

class TestInferenceResult:
    def test_top_detection_returns_highest_confidence(self):
        result = InferenceResult(
            model_name="test",
            model_version="0",
            detections=[
                Detection("animal", 0.75, [0.1, 0.1, 0.9, 0.9], "white-tailed deer"),
                Detection("animal", 0.45, [0.2, 0.2, 0.8, 0.8], None),
            ],
        )
        assert result.top_detection.confidence == 0.75
        assert result.top_species == "white-tailed deer"

    def test_empty_result_top_detection_is_none(self):
        result = InferenceResult(model_name="test", model_version="0")
        assert result.top_detection is None
        assert result.top_label is None
        assert result.top_confidence == 0.0

    def test_to_dict_structure(self):
        result = InferenceResult(
            model_name="MockDetector",
            model_version="0.0.0-mock",
            detections=[Detection("animal", 0.88, [0.1, 0.2, 0.7, 0.8], "raccoon")],
        )
        d = result.to_dict()
        assert d["model_name"] == "MockDetector"
        assert d["top_label"] == "animal"
        assert d["top_confidence"] == 0.88
        assert d["top_species"] == "raccoon"
        assert len(d["detections"]) == 1


# ── MockDetector ──────────────────────────────────────────────────────────────

class TestMockDetector:
    def test_detect_returns_inference_result(self, tmp_path):
        detector = MockDetector()
        fake_image = tmp_path / "test.jpg"
        fake_image.write_bytes(b"\xff\xd8\xff")  # minimal JPEG magic bytes
        result = detector.detect(fake_image)
        assert isinstance(result, InferenceResult)
        assert result.model_name == "mock_detector"

    def test_detect_is_deterministic(self, tmp_path):
        detector = MockDetector()
        fake_image = tmp_path / "stable.jpg"
        fake_image.write_bytes(b"\xff\xd8\xff")
        r1 = detector.detect(fake_image)
        r2 = detector.detect(fake_image)
        assert r1.detections == r2.detections

    def test_different_paths_can_differ(self, tmp_path):
        detector = MockDetector(empty_probability=0.0)
        img_a = tmp_path / "alpha.jpg"
        img_b = tmp_path / "beta.jpg"
        img_a.write_bytes(b"\xff\xd8\xff")
        img_b.write_bytes(b"\xff\xd8\xff")
        # Seeded from path — alpha and beta produce different seeds
        r_a = detector.detect(img_a)
        r_b = detector.detect(img_b)
        # Different paths → different seeds → may differ (not guaranteed but very likely)
        # We only assert that results are valid
        assert r_a.model_name == "mock_detector"
        assert r_b.model_name == "mock_detector"

    def test_is_always_available(self):
        assert MockDetector().is_available is True


# ── MegaDetectorV5 (availability check only — no weights in CI) ───────────────

class TestMegaDetectorV5Availability:
    def test_unavailable_when_weights_absent(self, tmp_path):
        md = MegaDetectorV5(weights_path=tmp_path / "nonexistent.pt")
        assert md.is_available is False

    def test_detect_raises_when_unavailable(self, tmp_path):
        md = MegaDetectorV5(weights_path=tmp_path / "nonexistent.pt")
        with pytest.raises(RuntimeError, match="weights not found"):
            md.detect(tmp_path / "any.jpg")

    def test_model_name(self):
        assert MegaDetectorV5().model_name == "MegaDetector"


# ── get_detector factory ──────────────────────────────────────────────────────

class TestGetDetector:
    def test_falls_back_to_mock_when_no_weights(self):
        detector = get_detector(weights_path=Path("/nonexistent/md_v5.pt"))
        assert isinstance(detector, MockDetector)


# ── InferencePipeline ─────────────────────────────────────────────────────────

class TestInferencePipeline:
    def test_run_stores_result_in_db(self, tmp_db, tmp_path):
        fake_image = tmp_path / "cap-001.jpg"
        fake_image.write_bytes(b"\xff\xd8\xff")

        pipeline = InferencePipeline(db=tmp_db, detector=MockDetector(), enabled=True)

        # Need an event in the DB first (FK constraint)
        tmp_db.upsert_device({
            "device_id": "node-x",
            "device_type": "node",
            "name": "X",
            "status": "active",
            "created_at": "2026-05-13T00:00:00Z",
            "last_seen_at": "2026-05-13T00:00:00Z",
        })
        tmp_db.add_event({
            "event_id": "evt-pipe-001",
            "event_type": "capture",
            "device_id": "node-x",
            "timestamp": "2026-05-13T06:00:00Z",
            "time_source": "rtc",
            "source": "node",
        })

        result = pipeline.run("evt-pipe-001", str(fake_image))
        assert result is not None
        stored = tmp_db.get_inference_result("evt-pipe-001")
        assert stored is not None
        assert stored["model_name"] == "mock_detector"

    def test_run_skips_missing_file(self, tmp_db):
        pipeline = InferencePipeline(db=tmp_db, detector=MockDetector(), enabled=True)
        result = pipeline.run("evt-x", "/nonexistent/image.jpg")
        assert result is None

    def test_run_skips_non_image(self, tmp_db, tmp_path):
        txt = tmp_path / "data.txt"
        txt.write_text("not an image")
        pipeline = InferencePipeline(db=tmp_db, detector=MockDetector(), enabled=True)
        result = pipeline.run("evt-y", str(txt))
        assert result is None

    def test_run_when_disabled_returns_none(self, tmp_db, tmp_path):
        fake_image = tmp_path / "cap.jpg"
        fake_image.write_bytes(b"\xff\xd8\xff")
        pipeline = InferencePipeline(db=tmp_db, detector=MockDetector(), enabled=False)
        result = pipeline.run("evt-z", str(fake_image))
        assert result is None

    def test_run_tolerates_detector_error(self, tmp_db, tmp_path):
        """Pipeline must not raise even if detector throws."""
        class BrokenDetector(MockDetector):
            def detect(self, path):
                raise RuntimeError("model exploded")

        fake_image = tmp_path / "cap.jpg"
        fake_image.write_bytes(b"\xff\xd8\xff")
        pipeline = InferencePipeline(db=tmp_db, detector=BrokenDetector(), enabled=True)
        result = pipeline.run("evt-broken", str(fake_image))
        assert result is None


# ── Database inference methods ────────────────────────────────────────────────

class TestInferenceDatabaseMethods:
    def _seed_event(self, db: GatewayDatabase, event_id: str, device_id: str = "node-y") -> None:
        db.upsert_device({
            "device_id": device_id,
            "device_type": "node",
            "name": "Y",
            "status": "active",
            "created_at": "2026-05-13T00:00:00Z",
            "last_seen_at": "2026-05-13T00:00:00Z",
        })
        db.add_event({
            "event_id": event_id,
            "event_type": "capture",
            "device_id": device_id,
            "timestamp": "2026-05-13T06:00:00Z",
            "time_source": "rtc",
            "source": "node",
        })

    def test_save_and_get_result(self, tmp_db):
        self._seed_event(tmp_db, "evt-db-001")
        result = InferenceResult(
            model_name="mock_detector",
            model_version="0.0.0-mock",
            detections=[Detection("animal", 0.91, [0.1, 0.1, 0.9, 0.9], "coyote")],
        )
        tmp_db.save_inference_result("evt-db-001", "/media/cap.jpg", result)
        stored = tmp_db.get_inference_result("evt-db-001")
        assert stored["top_label"] == "animal"
        assert stored["top_species"] == "coyote"
        assert abs(stored["top_confidence"] - 0.91) < 0.001

    def test_get_result_missing_returns_none(self, tmp_db):
        assert tmp_db.get_inference_result("no-such-event") is None

    def test_list_results_by_label(self, tmp_db):
        for i, (label, species) in enumerate([
            ("animal", "deer"), ("person", None), ("animal", "raccoon")
        ]):
            eid = f"evt-list-{i:03d}"
            self._seed_event(tmp_db, eid, device_id=f"node-list-{i}")
            r = InferenceResult("mock_detector", "0.0.0-mock",
                                [Detection(label, 0.8, [0, 0, 1, 1], species)])
            tmp_db.save_inference_result(eid, f"/media/{eid}.jpg", r)

        animals = tmp_db.list_inference_results(label="animal")
        assert all(r["top_label"] == "animal" for r in animals)
        assert len(animals) == 2

    def test_list_results_min_confidence(self, tmp_db):
        self._seed_event(tmp_db, "evt-conf-low")
        self._seed_event(tmp_db, "evt-conf-high", device_id="node-conf-high")
        low = InferenceResult("mock_detector", "0", [Detection("animal", 0.3, [0,0,1,1], None)])
        high = InferenceResult("mock_detector", "0", [Detection("animal", 0.9, [0,0,1,1], None)])
        tmp_db.save_inference_result("evt-conf-low", "/m/low.jpg", low)
        tmp_db.save_inference_result("evt-conf-high", "/m/high.jpg", high)
        results = tmp_db.list_inference_results(min_confidence=0.5)
        assert all(r["top_confidence"] >= 0.5 for r in results)


# ── Media upload endpoint ─────────────────────────────────────────────────────

class TestMediaUploadEndpoint:
    def test_upload_triggers_inference(self, registered_device_with_event):
        client, db, config, device_id, event_id = registered_device_with_event
        minimal_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
        resp = client.post(
            f"/api/v1/media/{event_id}",
            files={"file": ("capture.jpg", io.BytesIO(minimal_jpeg), "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["event_id"] == event_id
        assert "inference" in data

    def test_upload_saves_file_to_media_dir(self, registered_device_with_event):
        client, db, config, device_id, event_id = registered_device_with_event
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
        client.post(
            f"/api/v1/media/{event_id}",
            files={"file": ("cap.jpg", io.BytesIO(content), "image/jpeg")},
        )
        saved = config.media_dir / f"{event_id}.jpg"
        assert saved.exists()
        assert saved.read_bytes() == content

    def test_upload_unknown_event_still_saves(self, app_and_db):
        """Uploading for an unknown event saves the file; inference may fail silently."""
        client, db, config = app_and_db
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"
        resp = client.post(
            "/api/v1/media/evt-unknown-999",
            files={"file": ("cap.jpg", io.BytesIO(content), "image/jpeg")},
        )
        # Should not crash the server
        assert resp.status_code == 200


# ── Inference REST endpoints ──────────────────────────────────────────────────

class TestInferenceEndpoints:
    def test_get_event_inference_404_when_missing(self, registered_device_with_event):
        client, db, config, device_id, event_id = registered_device_with_event
        resp = client.get(f"/api/v1/events/{event_id}/inference")
        assert resp.status_code == 404

    def test_get_event_inference_after_direct_db_write(self, registered_device_with_event):
        client, db, config, device_id, event_id = registered_device_with_event
        result = InferenceResult(
            "mock_detector", "0.0.0-mock",
            [Detection("animal", 0.87, [0.1, 0.1, 0.9, 0.9], "wild turkey")],
        )
        db.save_inference_result(event_id, "/media/cap.jpg", result)
        resp = client.get(f"/api/v1/events/{event_id}/inference")
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["top_label"] == "animal"
        assert data["result"]["top_species"] == "wild turkey"

    def test_recent_inference_empty(self, app_and_db):
        client, db, config = app_and_db
        resp = client.get("/api/v1/inference/recent")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_recent_inference_with_label_filter(self, registered_device_with_event):
        client, db, config, device_id, event_id = registered_device_with_event
        db.save_inference_result(
            event_id, "/m/cap.jpg",
            InferenceResult("mock_detector", "0", [Detection("animal", 0.9, [0,0,1,1], "deer")])
        )
        resp = client.get("/api/v1/inference/recent?label=animal&min_confidence=0.5")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

        resp2 = client.get("/api/v1/inference/recent?label=person")
        assert resp2.json()["count"] == 0


# ── MCP tool functions ────────────────────────────────────────────────────────

class TestInferenceToolFunctions:
    def _context(self, tmp_db: GatewayDatabase) -> ToolContext:
        return ToolContext(database_path=tmp_db.path)

    def _seed(self, tmp_db: GatewayDatabase, event_id: str, label: str, species: str | None, confidence: float):
        tmp_db.upsert_device({
            "device_id": f"dev-{event_id}",
            "device_type": "node",
            "name": "T",
            "status": "active",
            "created_at": "2026-05-13T00:00:00Z",
            "last_seen_at": "2026-05-13T00:00:00Z",
        })
        tmp_db.add_event({
            "event_id": event_id,
            "event_type": "capture",
            "device_id": f"dev-{event_id}",
            "timestamp": "2026-05-13T06:00:00Z",
            "time_source": "rtc",
            "source": "node",
        })
        tmp_db.save_inference_result(
            event_id, f"/m/{event_id}.jpg",
            InferenceResult("mock_detector", "0", [Detection(label, confidence, [0,0,1,1], species)])
        )

    def test_get_inference_results_ok(self, tmp_db):
        self._seed(tmp_db, "evt-tool-001", "animal", "coyote", 0.82)
        ctx = self._context(tmp_db)
        result = get_inference_results(ctx, "evt-tool-001")
        assert result["ok"] is True
        assert result["result"]["top_label"] == "animal"

    def test_get_inference_results_missing(self, tmp_db):
        ctx = self._context(tmp_db)
        result = get_inference_results(ctx, "evt-not-there")
        assert result["ok"] is False
        assert "error" in result

    def test_list_species_detections_counts(self, tmp_db):
        self._seed(tmp_db, "evt-sp-001", "animal", "deer", 0.9)
        self._seed(tmp_db, "evt-sp-002", "animal", "deer", 0.75)
        self._seed(tmp_db, "evt-sp-003", "person", None, 0.6)
        ctx = self._context(tmp_db)
        result = list_species_detections(ctx, limit=10, min_confidence=0.5)
        assert result["ok"] is True
        assert result["label_counts"]["animal"] == 2
        assert result["species_counts"]["deer"] == 2

    def test_list_species_detections_species_filter(self, tmp_db):
        self._seed(tmp_db, "evt-sp-004", "animal", "white-tailed deer", 0.88)
        self._seed(tmp_db, "evt-sp-005", "animal", "raccoon", 0.71)
        ctx = self._context(tmp_db)
        result = list_species_detections(ctx, species="deer", min_confidence=0.0)
        assert result["count"] == 1
        assert result["results"][0]["top_species"] == "white-tailed deer"
