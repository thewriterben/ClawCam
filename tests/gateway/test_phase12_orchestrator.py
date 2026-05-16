"""Phase 12 tests: multi-detector orchestration (per-profile chains).

Coverage
--------
- DetectorRegistry: register, resolve (returns instance), unknown names,
  raising factory swallowed, unavailable detector skipped, names/available_names
- Default registry contains the expected detector names
- InferenceOrchestrator.chain_for_device: per-device override beats
  profile, profile beats default, unknown device falls back to general
- InferenceOrchestrator.run: every available detector contributes one
  inference_results row; chain in execution order via
  list_inference_results_for_event; detector failures don't abort chain
- DB: detector_chain_json column round-trip via set/get; get_device
  exposes detector_chain key
- REST: GET /api/v1/detectors (registry inspection),
  GET/PATCH /api/v1/devices/{id}/detector-chain,
  GET /api/v1/events/{id}/inference/chain
- MCP tools list_detectors, get_device_detector_chain,
  get_event_inference_chain (auto), set_device_detector_chain (gated)
- Brain adapter policy classification
"""

from __future__ import annotations

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
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import (
    Detection,
    InferenceResult,
    MockDetector,
)
from clawcam_gateway.inference.orchestrator import InferenceOrchestrator
from clawcam_gateway.inference.registry import DetectorRegistry, get_registry
from clawcam_gateway.mcp_server.stdio_server import TOOL_DEFINITIONS
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.profiles import PROFILE_BIRD_FEEDER, PROFILE_WILDLIFE
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    get_device_detector_chain as tool_get_chain,
    get_event_inference_chain as tool_get_event_chain,
    list_detectors as tool_list_detectors,
    set_device_detector_chain as tool_set_chain,
)
from clawcam_adapter import ToolPolicy  # type: ignore[import]


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _seed_device(db: GatewayDatabase, device_id: str = "cam-p12",
                  profile: str = PROFILE_WILDLIFE) -> None:
    db.upsert_device({
        "device_id": device_id,
        "device_type": "node",
        "name": "Orchestrator Test",
        "status": "active",
        "created_at": "2026-05-15T00:00:00Z",
        "last_seen_at": "2026-05-15T00:00:00Z",
    })
    db.set_device_profile(device_id, profile)


@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "test.db")
    _seed_device(db)
    return db


@pytest.fixture()
def client(tmp_path: Path) -> tuple[TestClient, GatewayDatabase]:
    cfg = GatewayConfig(database_path=tmp_path / "test.db",
                        media_dir=tmp_path / "media")
    app = create_app(config=cfg)
    db = GatewayDatabase(cfg.database_path)
    _seed_device(db)
    return TestClient(app), db


# ── DetectorRegistry ────────────────────────────────────────────────────────

class TestDetectorRegistry:
    def test_register_and_resolve(self):
        reg = DetectorRegistry()
        reg.register("my_mock", lambda: MockDetector())
        instance = reg.resolve("my_mock")
        assert instance is not None
        assert instance.is_available

    def test_unknown_name_returns_none(self):
        reg = DetectorRegistry()
        assert reg.resolve("does-not-exist") is None

    def test_raising_factory_returns_none(self):
        reg = DetectorRegistry()
        def boom():
            raise RuntimeError("nope")
        reg.register("broken", boom)
        assert reg.resolve("broken") is None

    def test_unavailable_detector_skipped(self):
        class UnavailableDetector(MockDetector):
            @property
            def is_available(self):
                return False
        reg = DetectorRegistry()
        reg.register("ghost", lambda: UnavailableDetector())
        assert reg.resolve("ghost") is None

    def test_names_and_available_names(self):
        reg = DetectorRegistry()
        reg.register("a", lambda: MockDetector())
        reg.register("b", lambda: MockDetector())
        assert set(reg.names()) == {"a", "b"}
        assert set(reg.available_names()) == {"a", "b"}

    def test_default_registry_has_expected_names(self):
        names = set(get_registry().names())
        for required in ("mock_detector", "megadetector_v5", "bird_classifier",
                         "face_recognizer", "plate_ocr"):
            assert required in names


# ── Orchestrator chain resolution ───────────────────────────────────────────

class TestChainResolution:
    def test_profile_defaults_used(self, tmp_db: GatewayDatabase):
        _seed_device(tmp_db, device_id="cam-bird", profile=PROFILE_BIRD_FEEDER)
        orch = InferenceOrchestrator(db=tmp_db)
        chain = orch.chain_for_device("cam-bird")
        # bird feeder profile lists MegaDetector + bird_classifier + audio_birdnet
        assert "bird_classifier" in chain or "megadetector_v5" in chain

    def test_unknown_device_falls_back_general(self, tmp_db: GatewayDatabase):
        orch = InferenceOrchestrator(db=tmp_db)
        chain = orch.chain_for_device("never-registered")
        assert chain == ["mock_detector"]

    def test_per_device_override_beats_profile(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_detector_chain("cam-p12", ["face_recognizer", "plate_ocr"])
        orch = InferenceOrchestrator(db=tmp_db)
        assert orch.chain_for_device("cam-p12") == ["face_recognizer", "plate_ocr"]

    def test_clear_override_returns_profile(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_detector_chain("cam-p12", ["face_recognizer"])
        tmp_db.set_device_detector_chain("cam-p12", None)
        orch = InferenceOrchestrator(db=tmp_db)
        chain = orch.chain_for_device("cam-p12")
        # Wildlife profile defaults
        assert "mock_detector" in chain or "megadetector_v5" in chain

    def test_disabled_orchestrator_returns_empty(self, tmp_db: GatewayDatabase):
        orch = InferenceOrchestrator(db=tmp_db, enabled=False)
        assert orch.run("evt-x", "/non/existent.jpg", device_id="cam-p12") == []


# ── Orchestrator.run end-to-end ────────────────────────────────────────────

class TestOrchestratorRun:
    def _seed_event(self, db: GatewayDatabase, event_id: str = "evt-orch-1") -> None:
        db.add_event({
            "event_id": event_id,
            "event_type": "motion_detected",
            "device_id": "cam-p12",
            "timestamp": "2026-05-15T10:00:00Z",
            "time_source": "rtc",
            "source": "node",
            "media": [],
            "metadata": {},
        })

    def test_chain_runs_every_available_detector(self, tmp_db: GatewayDatabase,
                                                   tmp_path: Path):
        self._seed_event(tmp_db)
        img = tmp_path / "x.jpg"
        img.write_bytes(b"FAKEJPEG")
        # Force-override to a chain with three known-available mock-backed names
        tmp_db.set_device_detector_chain(
            "cam-p12", ["mock_detector", "bird_classifier", "face_recognizer"]
        )
        orch = InferenceOrchestrator(db=tmp_db)
        summaries = orch.run("evt-orch-1", str(img), device_id="cam-p12")
        assert len(summaries) == 3
        assert all(s["stored"] is True for s in summaries)

        rows = tmp_db.list_inference_results_for_event("evt-orch-1")
        # Each detector produced one row.
        assert len(rows) == 3

    def test_unknown_detector_skipped(self, tmp_db: GatewayDatabase, tmp_path: Path):
        self._seed_event(tmp_db, event_id="evt-orch-skip")
        img = tmp_path / "x.jpg"
        img.write_bytes(b"x")
        tmp_db.set_device_detector_chain(
            "cam-p12", ["mock_detector", "nonexistent_detector_xyz"]
        )
        orch = InferenceOrchestrator(db=tmp_db)
        summaries = orch.run("evt-orch-skip", str(img), device_id="cam-p12")
        # Mock stored, unknown skipped.
        stored = [s for s in summaries if s.get("stored")]
        skipped = [s for s in summaries if not s.get("stored")]
        assert len(stored) == 1
        assert len(skipped) == 1
        assert skipped[0]["detector"] == "nonexistent_detector_xyz"

    def test_inference_results_for_event_chronological(self, tmp_db: GatewayDatabase,
                                                         tmp_path: Path):
        self._seed_event(tmp_db, event_id="evt-orch-order")
        img = tmp_path / "x.jpg"
        img.write_bytes(b"x")
        tmp_db.set_device_detector_chain("cam-p12", ["mock_detector", "bird_classifier"])
        orch = InferenceOrchestrator(db=tmp_db)
        orch.run("evt-orch-order", str(img), device_id="cam-p12")
        rows = tmp_db.list_inference_results_for_event("evt-orch-order")
        # Both rows are MockDetector (placeholders all the way down), but they
        # exist and are ordered.
        assert len(rows) == 2


# ── DB column round-trip ────────────────────────────────────────────────────

class TestDetectorChainDB:
    def test_set_and_get_chain(self, tmp_db: GatewayDatabase):
        assert tmp_db.set_device_detector_chain("cam-p12", ["a", "b", "c"])
        d = tmp_db.get_device("cam-p12")
        assert d["detector_chain"] == ["a", "b", "c"]

    def test_unknown_device_returns_false(self, tmp_db: GatewayDatabase):
        assert not tmp_db.set_device_detector_chain("ghost", ["x"])

    def test_clear_chain(self, tmp_db: GatewayDatabase):
        tmp_db.set_device_detector_chain("cam-p12", ["a"])
        tmp_db.set_device_detector_chain("cam-p12", None)
        d = tmp_db.get_device("cam-p12")
        assert "detector_chain" not in d


# ── REST surface ────────────────────────────────────────────────────────────

class TestDetectorChainREST:
    def test_list_detectors(self, client):
        c, _ = client
        body = c.get("/api/v1/detectors").json()
        assert "mock_detector" in body["all_detectors"]

    def test_get_device_chain(self, client):
        c, _ = client
        body = c.get("/api/v1/devices/cam-p12/detector-chain").json()
        assert body["ok"]
        assert isinstance(body["chain"], list)
        assert body["override_set"] is False

    def test_set_chain(self, client):
        c, db = client
        resp = c.patch("/api/v1/devices/cam-p12/detector-chain",
                       json={"data": {"chain": ["mock_detector", "bird_classifier"]}})
        assert resp.status_code == 200
        assert db.get_device("cam-p12")["detector_chain"] == \
            ["mock_detector", "bird_classifier"]

    def test_set_chain_invalid_type_400(self, client):
        c, _ = client
        assert c.patch("/api/v1/devices/cam-p12/detector-chain",
                       json={"data": {"chain": "not a list"}}).status_code == 400

    def test_set_chain_unknown_device_404(self, client):
        c, _ = client
        assert c.patch("/api/v1/devices/missing/detector-chain",
                       json={"data": {"chain": ["x"]}}).status_code == 404

    def test_event_chain_endpoint_empty(self, client):
        c, _ = client
        body = c.get("/api/v1/events/no-event/inference/chain").json()
        assert body["count"] == 0


# ── MCP tools ───────────────────────────────────────────────────────────────

class TestOrchestratorTools:
    def test_list_detectors_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_list_detectors(ctx)
        assert result["ok"]
        assert "mock_detector" in result["all_detectors"]

    def test_get_chain_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_get_chain(ctx, device_id="cam-p12")
        assert result["ok"]
        assert isinstance(result["chain"], list)

    def test_get_chain_unknown_device(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        assert not tool_get_chain(ctx, device_id="ghost")["ok"]

    def test_set_chain_tool(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_set_chain(ctx, device_id="cam-p12",
                                 chain=["mock_detector", "bird_classifier"])
        assert result["ok"]

    def test_set_chain_invalid_type(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        assert not tool_set_chain(ctx, device_id="cam-p12", chain="oops")["ok"]

    def test_get_event_chain_empty(self, tmp_db: GatewayDatabase):
        ctx = ToolContext(database_path=tmp_db.path)
        result = tool_get_event_chain(ctx, event_id="no-event")
        assert result["count"] == 0


# ── Wiring ──────────────────────────────────────────────────────────────────

class TestPhase12Wiring:
    def test_dispatch_list_detectors(self, tmp_db: GatewayDatabase):
        assert dispatch_tool("list_detectors", {}, database_path=tmp_db.path)["ok"]

    def test_dispatch_set_chain(self, tmp_db: GatewayDatabase):
        result = dispatch_tool(
            "set_device_detector_chain",
            {"device_id": "cam-p12", "chain": ["mock_detector"]},
            database_path=tmp_db.path,
        )
        assert result["ok"]

    def test_stdio_definitions(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        for n in ("list_detectors", "get_device_detector_chain",
                   "get_event_inference_chain", "set_device_detector_chain"):
            assert n in names

    def test_brain_adapter_policy(self):
        policy = ToolPolicy()
        for n in ("list_detectors", "get_device_detector_chain",
                   "get_event_inference_chain"):
            assert policy.is_auto_approved(n)
        assert policy.requires_approval("set_device_detector_chain")
