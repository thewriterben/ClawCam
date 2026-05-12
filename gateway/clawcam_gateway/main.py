"""Command-line entrypoint for the ClawCam gateway."""

from __future__ import annotations

import uvicorn

from clawcam_gateway.config import GatewayConfig


def main() -> None:
    config = GatewayConfig.from_env()
    uvicorn.run(
        "clawcam_gateway.api.app:app",
        host=config.host,
        port=config.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
