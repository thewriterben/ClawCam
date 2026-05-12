"""CLI entrypoint for generating ClawCam simulator payload bundles."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from clawcam_gateway.simulator.node_simulator import SimulatedNode


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ClawCam node simulator payloads.")
    parser.add_argument("--output", default="samples/node-simulator", help="Directory to write payloads into.")
    parser.add_argument("--device-id", default="node-001", help="Simulated node ID.")
    parser.add_argument("--deployment-id", default="deploy-north-ridge-2026", help="Deployment ID.")
    parser.add_argument("--name", default="North Ridge Camera", help="Human-readable node name.")
    args = parser.parse_args()

    node = SimulatedNode(device_id=args.device_id, deployment_id=args.deployment_id, name=args.name)
    paths = node.write_bundle(args.output, datetime.now(timezone.utc))
    for payload_type, path in paths.items():
        print(f"{payload_type}: {path}")


if __name__ == "__main__":
    main()
