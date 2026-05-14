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
        )
