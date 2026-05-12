from __future__ import annotations

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig


def test_gateway_device_event_health_flow(tmp_path) -> None:
    app = create_app(GatewayConfig(database_path=tmp_path / "gateway.db", media_dir=tmp_path / "media"))
    client = TestClient(app)

    device = {
        "device_id": "node-001",
        "device_type": "node",
        "name": "North Ridge Camera",
        "status": "active",
        "created_at": "2026-05-12T12:00:00Z",
        "last_seen_at": "2026-05-12T12:01:00Z",
    }
    response = client.post("/api/v1/devices", json={"data": device})
    assert response.status_code == 200, response.text
    assert response.json()["device_id"] == "node-001"

    event = {
        "event_id": "evt-001",
        "event_type": "capture",
        "device_id": "node-001",
        "timestamp": "2026-05-12T12:02:00Z",
        "time_source": "rtc",
        "source": "node",
        "media": [
            {
                "media_id": "img-001",
                "media_type": "image",
                "path": "/media/img-001.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": 123456,
            }
        ],
    }
    response = client.post("/api/v1/events", json={"data": event})
    assert response.status_code == 200, response.text
    assert response.json()["event_id"] == "evt-001"

    response = client.get("/api/v1/detections/recent")
    assert response.status_code == 200
    detections = response.json()["detections"]
    assert len(detections) == 1
    assert detections[0]["event_id"] == "evt-001"

    health = {
        "device_id": "node-001",
        "timestamp": "2026-05-12T12:03:00Z",
        "status": "ok",
        "battery": {"voltage": 3.91, "percentage": 72},
    }
    response = client.post("/api/v1/health", json={"data": health})
    assert response.status_code == 200, response.text

    response = client.get("/api/v1/devices/node-001/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
