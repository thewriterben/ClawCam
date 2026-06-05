"""Phase 13 WS4 — golden detection-pipeline eval (release gate).

End-to-end flow on deterministic mocks: device → event → media upload →
MockDetector inference → alert rule match → alert recorded. Pins both
*determinism* (identical inputs ⇒ identical outputs) and *structural
goldens* (exactly one inference row per event, alert fired with correct
linkage, valid confidence bounds) so pipeline drift fails CI.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.detector import MockDetector
from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase

JPEG_BYTES = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")


def _setup(tmp_path) -> tuple[TestClient, dict]:
    """Seed a gateway via the simulator; return a TestClient and a valid
    event template taken from the simulator's schema-valid output."""

    db_path = tmp_path / "gateway.db"
    bundle = tmp_path / "bundle"
    SimulatedNode(device_id="eval-cam").write_bundle(
        bundle, datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    )
    import_directory(bundle, GatewayDatabase(db_path))

    event_files = sorted(bundle.glob("event-*.json"))
    assert event_files, "simulator produced no event files"
    template = json.loads(event_files[0].read_text())

    config = GatewayConfig(
        database_path=db_path,
        media_dir=tmp_path / "media",
        mqtt_enabled=False,
        cloud_enabled=False,
    )
    return TestClient(create_app(config)), template


def _post_event_with_media(client: TestClient, template: dict, event_id: str) -> None:
    event = dict(template)
    event["event_id"] = event_id
    r = client.post("/api/v1/events", json={"data": event})
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/v1/media/{event_id}",
        files={"file": (f"{event_id}.jpg", JPEG_BYTES, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_eval_mock_detector_is_deterministic(tmp_path) -> None:
    """Same image path ⇒ identical detections, every time."""

    det = MockDetector()
    p = Path(tmp_path) / "fixed.jpg"
    first = det.detect(p)
    second = det.detect(p)
    assert [d.__dict__ for d in first.detections] == [d.__dict__ for d in second.detections]
    assert first.model_name == "mock_detector"
    for d in first.detections:
        assert 0.0 <= d.confidence <= 1.0


def test_eval_event_to_inference_golden(tmp_path) -> None:
    """One media upload ⇒ exactly one inference row with golden shape."""

    client, template = _setup(tmp_path)
    _post_event_with_media(client, template, "evt-eval-001")

    r = client.get("/api/v1/events/evt-eval-001/inference")
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["model_name"] == "mock_detector"
    assert result["event_id"] == "evt-eval-001"
    if result.get("top_confidence") is not None:
        assert 0.0 <= float(result["top_confidence"]) <= 1.0
    if result.get("top_label") is not None:
        assert result["top_label"] in {"animal", "person", "vehicle"}


def test_eval_inference_to_alert_golden(tmp_path) -> None:
    """A permissive rule fires when (and only when) a detection matches,
    and the fired alert links back to the rule and event."""

    client, template = _setup(tmp_path)

    r = client.post(
        "/api/v1/alert-rules",
        json={"data": {"name": "eval-any-animal", "label": "animal", "min_confidence": 0.0}},
    )
    assert r.status_code == 200, r.text
    rule_id = r.json()["rule"]["rule_id"]

    # The deterministic mock yields ~15% empty frames and 3 label classes;
    # bounded attempts guarantee an 'animal' detection without flakiness.
    fired_event = None
    for i in range(20):
        event_id = f"evt-eval-a{i:02d}"
        _post_event_with_media(client, template, event_id)
        inference = client.get(f"/api/v1/events/{event_id}/inference").json()["result"]
        alerts = client.get("/api/v1/alerts", params={"rule_id": rule_id}).json()["alerts"]
        if inference.get("top_label") == "animal":
            assert alerts, "animal detection did not fire the matching rule"
            fired_event = event_id
            break
        else:
            # Golden negative: non-matching labels must NOT fire this rule.
            assert not alerts

    assert fired_event, "no animal detection across 20 deterministic events"
    alert = client.get("/api/v1/alerts", params={"rule_id": rule_id}).json()["alerts"][0]
    assert alert["event_id"] == fired_event
    assert alert["rule_id"] == rule_id


def test_eval_pipeline_repeatable_with_identical_paths(tmp_path) -> None:
    """The full gateway pipeline is deterministic when media paths match:
    two fresh gateways with the same media layout produce the same label."""

    labels = []
    for run in range(2):
        run_dir = tmp_path / "same"  # same relative layout both runs
        if run_dir.exists():
            import shutil

            shutil.rmtree(run_dir)
        run_dir.mkdir()
        client, template = _setup(run_dir)
        _post_event_with_media(client, template, "evt-repeat-001")
        result = client.get("/api/v1/events/evt-repeat-001/inference").json()["result"]
        labels.append((result.get("top_label"), result.get("top_species")))

    assert labels[0] == labels[1], f"pipeline not deterministic: {labels}"
