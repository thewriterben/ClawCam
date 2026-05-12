"""Command-line import tools for ClawCam gateway development."""

from __future__ import annotations

import argparse
from pathlib import Path
import json
from typing import Any

from clawcam_gateway.ingest.validation import validate_device, validate_event, validate_health
from clawcam_gateway.storage.database import GatewayDatabase


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_payload(path: Path, db: GatewayDatabase) -> str:
    payload = load_json(path)
    if _looks_like_device(payload):
        validate_device(payload)
        db.upsert_device(payload)
        return f"device:{payload['device_id']}"
    if _looks_like_event(payload):
        validate_event(payload)
        if db.get_device(payload["device_id"]) is None:
            raise ValueError(f"event {payload['event_id']} references unknown device {payload['device_id']}")
        db.add_event(payload)
        return f"event:{payload['event_id']}"
    if _looks_like_health(payload):
        validate_health(payload)
        if db.get_device(payload["device_id"]) is None:
            raise ValueError(f"health payload references unknown device {payload['device_id']}")
        db.add_health(payload)
        return f"health:{payload['device_id']}"
    raise ValueError(f"could not infer ClawCam payload type for {path}")


def import_directory(directory: Path, db: GatewayDatabase) -> list[str]:
    json_files = sorted(directory.glob("*.json"))
    # Devices must be imported before events/health records.
    json_files.sort(key=lambda p: 0 if _looks_like_device(load_json(p)) else 1)
    imported: list[str] = []
    for path in json_files:
        imported.append(import_payload(path, db))
    return imported


def _looks_like_device(payload: dict[str, Any]) -> bool:
    return "device_type" in payload and "created_at" in payload and "name" in payload


def _looks_like_event(payload: dict[str, Any]) -> bool:
    return "event_id" in payload and "event_type" in payload and "source" in payload


def _looks_like_health(payload: dict[str, Any]) -> bool:
    return "status" in payload and "timestamp" in payload and "event_id" not in payload and "device_type" not in payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Import ClawCam sample payloads into a gateway database.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    import_sample = subcommands.add_parser("import-sample", help="Import a file or directory of JSON payloads.")
    import_sample.add_argument("path", help="Payload JSON file or directory containing payload JSON files.")
    import_sample.add_argument("--db", default="clawcam_gateway.db", help="SQLite gateway database path.")

    args = parser.parse_args()
    db = GatewayDatabase(args.db)
    path = Path(args.path)

    if args.command == "import-sample":
        if path.is_dir():
            imported = import_directory(path, db)
        else:
            imported = [import_payload(path, db)]
        for item in imported:
            print(f"imported {item}")


if __name__ == "__main__":
    main()
