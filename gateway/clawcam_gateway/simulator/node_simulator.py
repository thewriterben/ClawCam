"""Deterministic node simulator for ClawCam Phase 1 development.

The simulator creates schema-compatible payloads without requiring camera hardware. It is
intended to unlock gateway, import, dashboard, and brain-tool development before the real
ESP32 firmware capture loop is ported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import uuid


@dataclass(frozen=True)
class SimulatedNode:
    """Configuration for a deterministic simulated ClawCam node."""

    device_id: str = "node-001"
    deployment_id: str = "deploy-north-ridge-2026"
    name: str = "North Ridge Camera"
    latitude: float = 45.5123
    longitude: float = -110.9012
    altitude_m: float = 1492.0

    def device_payload(self, timestamp: datetime | None = None) -> dict[str, Any]:
        now = _iso(timestamp)
        return {
            "device_id": self.device_id,
            "device_type": "node",
            "name": self.name,
            "status": "active",
            "created_at": now,
            "last_seen_at": now,
            "deployment_id": self.deployment_id,
            "capabilities": ["capture", "motion", "battery", "storage", "environment"],
            "hardware": {
                "board": "esp32-s3-camera",
                "mcu": "esp32-s3",
                "camera": "ov2640",
                "psram_mb": 8,
                "storage": "microsd",
            },
            "firmware": {
                "name": "clawcam-node",
                "version": "0.1.0-sim",
                "build": "simulator",
                "source": "gateway.clawcam_gateway.simulator.node_simulator",
            },
            "location": self._location(),
            "metadata": {"profile": "phase1-simulator", "simulated": True},
        }

    def capture_event_payload(self, timestamp: datetime | None = None) -> dict[str, Any]:
        ts = timestamp or datetime.now(timezone.utc)
        safe_ts = ts.strftime("%Y%m%d-%H%M%S")
        media_id = f"img-{self.device_id}-{safe_ts}"
        event_id = f"evt-{self.device_id}-{safe_ts}-{uuid.uuid5(uuid.NAMESPACE_DNS, media_id).hex[:8]}"
        media_path = f"samples/media/{media_id}.jpg"
        return {
            "event_id": event_id,
            "event_type": "capture",
            "device_id": self.device_id,
            "deployment_id": self.deployment_id,
            "timestamp": _iso(ts),
            "time_source": "gateway",
            "source": "node",
            "media": [
                {
                    "media_id": media_id,
                    "media_type": "image",
                    "path": media_path,
                    "uri": None,
                    "mime_type": "image/jpeg",
                    "size_bytes": 1024,
                    "sha256": _stable_sha256(media_id),
                }
            ],
            "battery": {"voltage": 3.91, "percentage": 72, "charging": False},
            "environment": {
                "temperature_c": 11.8,
                "humidity_percent": 54.2,
                "pressure_hpa": 842.3,
                "lux": 38.0,
            },
            "location": self._event_location(),
            "classifications": [
                {
                    "classification_id": f"cls-{event_id}",
                    "label": "animal",
                    "scientific_name": None,
                    "taxon_id": None,
                    "confidence": 0.82,
                    "source": "node",
                    "model": {
                        "name": "clawcam-sim-filter",
                        "version": "0.1.0",
                        "runtime": "simulator",
                        "threshold": 0.6,
                    },
                    "review_state": "unreviewed",
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": "Simulated lightweight node-side animal filter.",
                }
            ],
            "metadata": {
                "trigger": "pir",
                "motion_score": 0.74,
                "capture_profile": "balanced",
                "simulated": True,
            },
        }

    def health_payload(self, timestamp: datetime | None = None) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "timestamp": _iso(timestamp),
            "status": "ok",
            "uptime_seconds": 420,
            "battery": {
                "voltage": 3.91,
                "percentage": 72,
                "charging": False,
                "estimated_hours_remaining": 96.0,
            },
            "storage": {
                "free_bytes": 14953358131,
                "used_bytes": 524288000,
                "total_bytes": 15477646131,
                "media_count": 1,
            },
            "radio": {
                "rssi": -61,
                "snr": 8.5,
                "packet_loss": 0.0,
                "last_seen_at": _iso(timestamp),
            },
            "environment": {
                "temperature_c": 11.8,
                "humidity_percent": 54.2,
                "pressure_hpa": 842.3,
            },
            "errors": [],
            "metadata": {"profile": "phase1-simulator", "simulated": True},
        }

    def bundle(self, timestamp: datetime | None = None) -> dict[str, dict[str, Any]]:
        ts = timestamp or datetime.now(timezone.utc)
        return {
            "device": self.device_payload(ts),
            "event": self.capture_event_payload(ts),
            "health": self.health_payload(ts),
        }

    def write_bundle(self, output_dir: str | Path, timestamp: datetime | None = None) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        bundle = self.bundle(timestamp)
        paths: dict[str, Path] = {}
        for name, payload in bundle.items():
            path = output / f"{name}-{self.device_id}.json"
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            paths[name] = path
        return paths

    def _location(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude_m": self.altitude_m,
            "sensitive": True,
            "label": "North Ridge",
        }

    def _event_location(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude_m": self.altitude_m,
            "sensitive": True,
        }


def _iso(timestamp: datetime | None = None) -> str:
    ts = timestamp or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
