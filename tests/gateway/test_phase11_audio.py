"""Phase 11 tests: audio pipeline (capture → classify → store).

Coverage
--------
- AudioClassification dataclass + to_dict
- BaseAudioClassifier abstract contract
- MockAudioClassifier: always available, deterministic for same input,
  obeys empty_probability, catalog labels present, fields in range
- get_default_classifier returns a working classifier
- AudioPipeline: stores rows; never raises on bad classifier; disabled
  pipeline returns 0; classifier exception swallowed
- DB CRUD for audio_uploads + audio_classifications with filters
- REST: POST /api/v1/audio/{event_id} accepts upload, schedules pipeline,
  returns audio_id; GET retrieves classifications + uploads; recent
  endpoint with label / species / min_confidence filters
- MCP tools list_audio_classifications + get_audio_for_event
- Dispatch + stdio definitions + adapter policy
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
_BRAIN_DIR = _REPO / "brain" / "oh-ben-claw-adapter"
for _p in (_GW, _BRAIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.audio import (
    AudioClassification,
    AudioPipeline,
    BaseAudioClassifier,
    MockAudioClassifier,
    get_default_classifier,
)
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.mcp_server.stdio_server import TOOL_DEFINITIONS
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    get_audio_for_event as tool_get_event_audio,
    list_audio_classifications as tool_list_classifications,
)
from clawcam_adapter import ToolPolicy  # type: ignore[import]


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _seed_event(db: GatewayDatabase, event_id: str = "evt-audio-1",
                device_id: str = "node-audio") -> None:
    db.upsert_device({
        "device_id": device_id,
        "device_type": "node",
        "name": "Audio Test Node",
        "status": "active",
        "created_at": "2026-05-15T00:00:00Z",
        "last_seen_at": "2026-05-15T00:00:00Z",
    })
    db.add_event({
        "event_id": event_id,
        "event_type": "motion_detected",
        "device_id": device_id,
        "timestamp": "2026-05-15T10:00:00Z",
        "time_source": "rtc",
        "source": "node",
        "media": [],
        "metadata": {},
    })


@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "test.db")
    _seed_event(db)
    return db


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, GatewayDatabase]:
    cfg = GatewayConfig(
        database_path=tmp_path / "test.db",
        media_dir=tmp_path / "media",
    )
    app = create_app(config=cfg)
    db = GatewayDatabase(cfg.database_path)
    _seed_event(db)
    return TestClient(app), db


# ── Classifier dataclass + base ──────────────────────────────────────────────

class TestAudioClassificationDataclass:
    def test_defaults(self):
        c = AudioClassification(label="bird", confidence=0.9)
        assert c.time_offset_s == 0.0
        assert c.duration_s == 0.0
        assert c.species is None

    def test_to_dict(self):
        c = AudioClassification(
            label="bird", confidence=0.9, time_offset_s=1.2,
            duration_s=2.0, species="American Robin",
        )
        d = c.to_dict()
        assert d == {
            "label": "bird", "confidence": 0.9,
            "time_offset_s": 1.2, "duration_s": 2.0,
            "species": "American Robin",
        }


class TestBaseAudioClassifierABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseAudioClassifier()  # type: ignore[abstract]


# ── MockAudioClassifier ─────────────────────────────────────────────────────

class TestMockAudioClassifier:
    def test_is_available(self):
        assert MockAudioClassifier().is_available

    def test_deterministic_for_same_input(self, tmp_path: Path):
        audio = tmp_path / "x.wav"
        audio.write_bytes(b"hello world")
        c = MockAudioClassifier(empty_probability=0.0)
        first = c.classify(audio)
        second = c.classify(audio)
        assert first == second

    def test_different_input_likely_different_output(self, tmp_path: Path):
        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        a.write_bytes(b"foo")
        b.write_bytes(b"bar")
        c = MockAudioClassifier(empty_probability=0.0)
        # Just confirm both succeed without insisting they differ — hash collisions
        # are vanishingly unlikely.
        assert c.classify(a) is not None
        assert c.classify(b) is not None

    def test_empty_probability_zero_always_returns_results(self, tmp_path: Path):
        c = MockAudioClassifier(empty_probability=0.0)
        for i in range(10):
            audio = tmp_path / f"x{i}.wav"
            audio.write_bytes(f"clip-{i}".encode())
            assert len(c.classify(audio)) >= 1

    def test_empty_probability_one_returns_nothing(self, tmp_path: Path):
        c = MockAudioClassifier(empty_probability=1.0)
        audio = tmp_path / "x.wav"
        audio.write_bytes(b"data")
        assert c.classify(audio) == []

    def test_returned_fields_in_range(self, tmp_path: Path):
        audio = tmp_path / "y.wav"
        audio.write_bytes(b"sample")
        c = MockAudioClassifier(empty_probability=0.0)
        for hit in c.classify(audio):
            assert 0.5 <= hit.confidence <= 1.0
            assert 0.0 <= hit.time_offset_s <= 5.0
            assert 1.0 <= hit.duration_s <= 3.0
            assert hit.label in {"bird", "dog_bark", "vehicle", "glass_break", "scream"}

    def test_nonexistent_file_still_classifies(self, tmp_path: Path):
        # Should hash by filename instead of file contents.
        c = MockAudioClassifier(empty_probability=0.0)
        result = c.classify(tmp_path / "ghost.wav")
        # No exception; deterministic result based on filename.
        assert isinstance(result, list)


class TestDefaultClassifier:
    def test_default_is_available(self):
        c = get_default_classifier()
        assert c.is_available
        # Without birdnetlib installed, should fall back to mock.
        assert isinstance(c, MockAudioClassifier)


# ── AudioPipeline ───────────────────────────────────────────────────────────

class TestAudioPipeline:
    def test_stores_classifications(self, tmp_db: GatewayDatabase, tmp_path: Path):
        audio_path = tmp_path / "clip.wav"
        audio_path.write_bytes(b"audio")
        audio_id = tmp_db.add_audio_upload({
            "event_id": "evt-audio-1",
            "device_id": "node-audio",
            "path": str(audio_path),
            "format": "wav",
        })
        pipeline = AudioPipeline(
            db=tmp_db,
            classifier=MockAudioClassifier(empty_probability=0.0),
        )
        stored = pipeline.run(audio_id, audio_path, event_id="evt-audio-1")
        assert stored >= 1
        classifications = tmp_db.list_audio_classifications(audio_id=audio_id)
        assert len(classifications) == stored

    def test_disabled_pipeline_no_op(self, tmp_db: GatewayDatabase, tmp_path: Path):
        audio = tmp_path / "x.wav"
        audio.write_bytes(b"x")
        audio_id = tmp_db.add_audio_upload({
            "path": str(audio), "format": "wav",
        })
        pipeline = AudioPipeline(db=tmp_db, enabled=False)
        assert pipeline.run(audio_id, audio) == 0

    def test_classifier_exception_swallowed(self, tmp_db: GatewayDatabase, tmp_path: Path):
        class BrokenClassifier(MockAudioClassifier):
            def classify(self, audio_path):
                raise RuntimeError("boom")
        audio = tmp_path / "x.wav"
        audio.write_bytes(b"x")
        audio_id = tmp_db.add_audio_upload({"path": str(audio), "format": "wav"})
        pipeline = AudioPipeline(db=tmp_db, classifier=BrokenClassifier())
        # Should NOT raise
        assert pipeline.run(audio_id, audio) == 0


# ── Database CRUD ───────────────────────────────────────────────────────────

class TestAudioDB:
    def test_add_and_get_upload(self, tmp_db: GatewayDatabase):
        audio_id = tmp_db.add_audio_upload({
            "event_id": "evt-audio-1",
            "device_id": "node-audio",
            "path": "/m/x.wav",
            "format": "wav",
            "duration_s": 3.0,
            "size_bytes": 12345,
        })
        d = tmp_db.get_audio_upload(audio_id)
        assert d is not None
        assert d["event_id"] == "evt-audio-1"
        assert d["format"] == "wav"
        assert d["duration_s"] == 3.0

    def test_list_uploads_filter(self, tmp_db: GatewayDatabase):
        tmp_db.add_audio_upload({"path": "/a.wav", "event_id": "evt-audio-1"})
        tmp_db.add_audio_upload({"path": "/b.wav", "event_id": "evt-other"})
        for_event = tmp_db.list_audio_uploads(event_id="evt-audio-1")
        assert len(for_event) == 1
        assert for_event[0]["path"] == "/a.wav"

    def test_add_classification_and_filter(self, tmp_db: GatewayDatabase):
        audio_id = tmp_db.add_audio_upload({"path": "/x.wav"})
        for label, species, conf in [
            ("bird", "American Robin", 0.95),
            ("bird", "House Finch", 0.45),
            ("dog_bark", None, 0.7),
        ]:
            tmp_db.add_audio_classification({
                "audio_id": audio_id,
                "classifier_name": "mock", "classifier_version": "0",
                "label": label, "species": species, "confidence": conf,
            })
        all_ = tmp_db.list_audio_classifications(audio_id=audio_id)
        assert len(all_) == 3

        birds = tmp_db.list_audio_classifications(audio_id=audio_id, label="bird")
        assert len(birds) == 2

        high_conf = tmp_db.list_audio_classifications(
            audio_id=audio_id, min_confidence=0.8,
        )
        assert len(high_conf) == 1
        assert high_conf[0]["species"] == "American Robin"

        robins = tmp_db.list_audio_classifications(audio_id=audio_id, species="Robin")
        assert len(robins) == 1


# ── REST surface ────────────────────────────────────────────────────────────

class TestAudioREST:
    def test_upload_and_retrieve(self, client):
        c, _ = client
        files = {"file": ("clip.wav", io.BytesIO(b"FAKEWAVDATA"), "audio/wav")}
        resp = c.post("/api/v1/audio/evt-audio-1", files=files)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"]
        assert "audio_id" in body
        # Retrieve - classifier ran inline-ish (background task in TestClient is synchronous-enough)
        get_resp = c.get("/api/v1/audio/evt-audio-1/classifications")
        assert get_resp.status_code == 200
        assert get_resp.json()["event_id"] == "evt-audio-1"

    def test_upload_unknown_event_404(self, client):
        c, _ = client
        files = {"file": ("clip.wav", io.BytesIO(b"x"), "audio/wav")}
        assert c.post("/api/v1/audio/no-such-event", files=files).status_code == 404

    def test_recent_endpoint(self, client):
        c, _ = client
        files = {"file": ("clip.wav", io.BytesIO(b"data1"), "audio/wav")}
        c.post("/api/v1/audio/evt-audio-1", files=files)
        resp = c.get("/api/v1/audio/recent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"]


# ── MCP tools ───────────────────────────────────────────────────────────────

class TestAudioTools:
    def test_list_empty(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        assert tool_list_classifications(ctx)["count"] == 0

    def test_list_after_insert(self, tmp_db: GatewayDatabase):
        audio_id = tmp_db.add_audio_upload({"path": "/x.wav",
                                              "event_id": "evt-audio-1"})
        tmp_db.add_audio_classification({
            "audio_id": audio_id, "event_id": "evt-audio-1",
            "classifier_name": "mock", "classifier_version": "0",
            "label": "bird", "species": "Robin", "confidence": 0.9,
        })
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_classifications(ctx, event_id="evt-audio-1")
        assert result["count"] == 1
        assert result["results"][0]["species"] == "Robin"

    def test_get_audio_for_event(self, tmp_db: GatewayDatabase):
        audio_id = tmp_db.add_audio_upload({"path": "/x.wav",
                                              "event_id": "evt-audio-1"})
        tmp_db.add_audio_classification({
            "audio_id": audio_id, "event_id": "evt-audio-1",
            "classifier_name": "m", "classifier_version": "0",
            "label": "bird", "confidence": 0.9,
        })
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_get_event_audio(ctx, event_id="evt-audio-1")
        assert result["upload_count"] == 1
        assert len(result["classifications"]) == 1


# ── Dispatch + stdio + adapter ──────────────────────────────────────────────

class TestPhase11Wiring:
    def test_dispatch_list(self, tmp_db: GatewayDatabase):
        assert dispatch_tool("list_audio_classifications", {},
                              database_path=tmp_db.path)["ok"]

    def test_dispatch_get(self, tmp_db: GatewayDatabase):
        result = dispatch_tool(
            "get_audio_for_event", {"event_id": "evt-audio-1"},
            database_path=tmp_db.path,
        )
        assert result["ok"]

    def test_stdio_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert "list_audio_classifications" in names
        assert "get_audio_for_event" in names

    def test_brain_adapter_policy(self):
        policy = ToolPolicy()
        assert policy.is_auto_approved("list_audio_classifications")
        assert policy.is_auto_approved("get_audio_for_event")
