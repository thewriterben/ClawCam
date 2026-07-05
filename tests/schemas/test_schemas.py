from __future__ import annotations

from pathlib import Path
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"
PAYLOAD_DIR = REPO_ROOT / "samples" / "payloads"


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
            "capabilities": ["cap_clawcam_camera_trap", "cap_clawcam_power",
                             "cap_clawcam_storage"],
            "hardware": {"board": "esp32-s3-camera", "psram_mb": 8},
            "firmware": {"name": "clawcam-node", "version": "0.1.0"},
        },
    )


def test_device_schema_rejects_legacy_capability_strings() -> None:
    """D-M5 guard: legacy short names ('capture', 'motion') must not validate.

    Gated commands match the canonical cap_clawcam_* tokens — a device
    registered with legacy names could never receive capture_now, and nothing
    caught it because the schema accepted any string.
    """
    for legacy in ("capture", "motion", "battery"):
        with pytest.raises(ValidationError):
            validate(
                "clawcam-device.schema.json",
                {
                    "device_id": "node-legacy",
                    "device_type": "node",
                    "name": "Legacy Device",
                    "status": "active",
                    "created_at": "2026-05-12T12:00:00Z",
                    "capabilities": [legacy],
                },
            )


# ── Sample payloads must validate against their schemas (D-M5 guard) ─────────
# A sample that drifts from the schema is worse than no sample: it teaches
# integrators a shape the gateway rejects (or silently cripples).

_SAMPLE_SCHEMA_MAP = {
    "device-node-001.json": "clawcam-device.schema.json",
    "event-capture-001.json": "clawcam-event.schema.json",
    "health-node-001.json": "clawcam-health.schema.json",
}


@pytest.mark.parametrize("sample_name,schema_name", sorted(_SAMPLE_SCHEMA_MAP.items()))
def test_sample_payloads_validate_against_schemas(sample_name: str,
                                                   schema_name: str) -> None:
    payload = json.loads((PAYLOAD_DIR / sample_name).read_text(encoding="utf-8"))
    validate(schema_name, payload)


def test_no_unmapped_sample_payloads() -> None:
    """Every sample payload must be schema-mapped above — new samples included."""
    actual = {p.name for p in PAYLOAD_DIR.glob("*.json")}
    assert actual == set(_SAMPLE_SCHEMA_MAP), (
        "sample payloads changed; update _SAMPLE_SCHEMA_MAP so they stay validated"
    )


def test_device_sample_can_receive_gated_capture() -> None:
    """The shipped device sample must be able to receive capture_now."""
    payload = json.loads((PAYLOAD_DIR / "device-node-001.json").read_text(encoding="utf-8"))
    assert "cap_clawcam_camera_trap" in payload["capabilities"]


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
