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
    # Cloud storage (off-site media archival)
    cloud_enabled: bool = False           # disabled by default; zero impact if not configured
    cloud_provider: str = "noop"          # "s3", "gcs", "noop"
    cloud_bucket: str = ""
    cloud_prefix: str = "clawcam/"       # remote key prefix
    cloud_region: str | None = None      # AWS region (S3 only)
    cloud_endpoint_url: str | None = None  # custom endpoint for MinIO / LocalStack
    # Alerting (webhook notifications on inference results)
    alert_webhook_url: str | None = None  # global default; rules may override per-rule
    # Authentication and multi-tenancy (Phase 7)
    auth_enabled: bool = False           # off by default; existing deployments unaffected
    default_deployment_id: str = "default"
    # Schedule engine (Phase 9)
    scheduler_enabled: bool = False      # opt-in; the engine's tick() is also driven
                                         # synchronously by tests and admin tools
    scheduler_tick_interval_s: int = 30
    # Audio pipeline (Phase 11)
    audio_enabled: bool = True           # mock classifier always works, so on by default

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
            cloud_enabled=os.getenv("CLAWCAM_CLOUD_ENABLED", "false").lower() == "true",
            cloud_provider=os.getenv("CLAWCAM_CLOUD_PROVIDER", "noop"),
            cloud_bucket=os.getenv("CLAWCAM_CLOUD_BUCKET", ""),
            cloud_prefix=os.getenv("CLAWCAM_CLOUD_PREFIX", "clawcam/"),
            cloud_region=os.getenv("CLAWCAM_CLOUD_REGION"),
            cloud_endpoint_url=os.getenv("CLAWCAM_CLOUD_ENDPOINT_URL"),
            alert_webhook_url=os.getenv("CLAWCAM_ALERT_WEBHOOK_URL") or None,
            auth_enabled=os.getenv("CLAWCAM_AUTH_ENABLED", "false").lower() == "true",
            default_deployment_id=os.getenv("CLAWCAM_DEFAULT_DEPLOYMENT", "default"),
            scheduler_enabled=os.getenv("CLAWCAM_SCHEDULER_ENABLED", "false").lower() == "true",
            scheduler_tick_interval_s=int(os.getenv("CLAWCAM_SCHEDULER_TICK_S", "30")),
            audio_enabled=os.getenv("CLAWCAM_AUDIO_ENABLED", "true").lower() != "false",
        )
