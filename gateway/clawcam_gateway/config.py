"""Gateway configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class GatewayConfig:
    """Runtime configuration for the ClawCam gateway."""

    database_path: Path = Path("clawcam_gateway.db")
    media_dir: Path = Path("media")
    host: str = "0.0.0.0"
    port: int = 8080
    gateway_id: str = "local-gateway"
    inference_enabled: bool = True
    inference_weights_path: Path | None = None  # None → auto-select (MegaDetector > Mock)
    mqtt_enabled: bool = False               # disabled by default; requires a running broker
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_client_id: str = "clawcam-gateway"
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_root: str = "clawcam"

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        weights_env = os.getenv("CLAWCAM_INFERENCE_WEIGHTS")
        return cls(
            database_path=Path(os.getenv("CLAWCAM_DB", "clawcam_gateway.db")),
            media_dir=Path(os.getenv("CLAWCAM_MEDIA_DIR", "media")),
            host=os.getenv("CLAWCAM_HOST", "0.0.0.0"),
            port=int(os.getenv("CLAWCAM_PORT", "8080")),
            gateway_id=os.getenv("CLAWCAM_GATEWAY_ID", "local-gateway"),
            inference_enabled=os.getenv("CLAWCAM_INFERENCE_ENABLED", "true").lower() != "false",
            inference_weights_path=Path(weights_env) if weights_env else None,
            mqtt_enabled=os.getenv("CLAWCAM_MQTT_ENABLED", "false").lower() == "true",
            mqtt_broker_host=os.getenv("CLAWCAM_MQTT_HOST", "localhost"),
            mqtt_broker_port=int(os.getenv("CLAWCAM_MQTT_PORT", "1883")),
            mqtt_client_id=os.getenv("CLAWCAM_MQTT_CLIENT_ID", "clawcam-gateway"),
            mqtt_username=os.getenv("CLAWCAM_MQTT_USERNAME"),
            mqtt_password=os.getenv("CLAWCAM_MQTT_PASSWORD"),
            mqtt_topic_root=os.getenv("CLAWCAM_MQTT_ROOT", "clawcam"),
        )
