from __future__ import annotations

from pathlib import Path
import json

from jsonschema import Draft202012Validator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validate(name: str, payload: dict) -> None:
    Draft202012Validator(load_schema(name)).validate(payload)


def test_device_schema_accepts_node_payload() -> None:
    validate(
        "clawcam-device.schema.json",
        {
            "device_id": "node-001",
            "device_type": "node",
            "name": "North Ridge Camera",
            "status": "active",
            "created_at": "2026-05-12T12:00:00Z",
            "last_seen_at": "2026-05-12T12:01:00Z",
            "capabilities": ["capture", "battery", "storage"],
            "hardware": {"board": "esp32-s3-camera", "psram_mb": 8},
            "firmware": {"name": "clawcam-node", "version": "0.1.0"},
        },
    )


def test_event_schema_accepts_capture_payload() -> None:
    validate(
        "clawcam-event.schema.json",
        {
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
            "battery": {"voltage": 3.91, "percentage": 72},
            "metadata": {"trigger": "pir"},
        },
    )


def test_observation_schema_accepts_reviewable_classification() -> None:
    validate(
        "clawcam-observation.schema.json",
        {
            "observation_id": "obs-001",
            "event_id": "evt-001",
            "device_id": "node-001",
            "timestamp": "2026-05-12T12:02:00Z",
            "media_ids": ["img-001"],
            "classifications": [
                {
                    "classification_id": "cls-001",
                    "label": "deer",
                    "source": "model",
                    "confidence": 0.91,
                    "review_state": "unreviewed",
                    "model": {"name": "example", "version": "0.0.1", "runtime": "gateway"},
                }
            ],
        },
    )


def test_health_schema_accepts_node_health() -> None:
    validate(
        "clawcam-health.schema.json",
        {
            "device_id": "node-001",
            "timestamp": "2026-05-12T12:03:00Z",
            "status": "ok",
            "uptime_seconds": 120,
            "battery": {"voltage": 3.91, "percentage": 72, "charging": False},
            "storage": {"free_bytes": 1000, "used_bytes": 2000, "total_bytes": 3000, "media_count": 1},
        },
    )
