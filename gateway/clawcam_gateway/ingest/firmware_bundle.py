"""Import firmware-generated ClawCam SD-card bundles into the gateway database."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
from typing import Any

from clawcam_gateway.ingest.validation import validate_device, validate_event
from clawcam_gateway.storage.database import GatewayDatabase


@dataclass(slots=True)
class FirmwareBundleImportResult:
    """Summary of a firmware SD-card bundle import run."""

    imported_events: list[str] = field(default_factory=list)
    registered_devices: list[str] = field(default_factory=list)
    copied_media: list[str] = field(default_factory=list)
    referenced_media: list[str] = field(default_factory=list)
    skipped_events: list[str] = field(default_factory=list)

    @property
    def event_count(self) -> int:
        return len(self.imported_events)

    @property
    def media_count(self) -> int:
        return len(self.copied_media) + len(self.referenced_media)


def import_firmware_bundle(
    bundle_root: Path,
    db: GatewayDatabase,
    media_dir: Path | None = None,
    copy_media: bool = True,
    auto_register_devices: bool = True,
) -> FirmwareBundleImportResult:
    """Import a firmware SD-card bundle into the gateway database.

    The expected bundle layout mirrors the firmware bench path:

    ```text
    bundle_root/
      events/*.json
      media/*.jpg
      metadata/*.json
    ```

    Event JSON files are validated against `clawcam-event.schema.json`. If an
    event references an unknown device, the importer can auto-register a
    conservative hardware node record so the normal gateway foreign-key guard is
    preserved without requiring a separate manual device payload.
    """

    root = Path(bundle_root)
    events_dir = root / "events"
    if not events_dir.exists() or not events_dir.is_dir():
        raise FileNotFoundError(f"firmware bundle is missing events directory: {events_dir}")

    destination_media_dir = Path(media_dir) if media_dir is not None else None
    if copy_media and destination_media_dir is None:
        destination_media_dir = root / "gateway_media"
    if copy_media and destination_media_dir is not None:
        destination_media_dir.mkdir(parents=True, exist_ok=True)

    result = FirmwareBundleImportResult()
    for event_path in sorted(events_dir.glob("*.json")):
        event = json.loads(event_path.read_text(encoding="utf-8"))
        validate_event(event)

        device_id = event["device_id"]
        if db.get_device(device_id) is None:
            if not auto_register_devices:
                raise ValueError(f"event {event['event_id']} references unknown device {device_id}")
            device = _device_from_event(event)
            validate_device(device)
            db.upsert_device(device)
            result.registered_devices.append(device_id)

        event = _resolve_media_paths(event, root, destination_media_dir, copy_media, result)
        validate_event(event)
        db.add_event(event)
        result.imported_events.append(event["event_id"])

    return result


def _device_from_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata", {})
    board = metadata.get("board_profile", "unknown")
    created_at = event.get("timestamp")
    if created_at == "1970-01-01T00:00:00Z":
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "device_id": event["device_id"],
        "device_type": "node",
        "name": f"Firmware node {event['device_id']}",
        "hardware": {
            "board": board,
            "mcu": "esp32-s3" if "esp32-s3" in board else "unknown",
            "camera": "ov2640" if "esp32-s3-eye" in board else "unknown",
            "storage": "sd/fatfs",
        },
        "firmware": {
            "name": "clawcam-node-espidf",
            "version": "0.1.0",
            "source": "firmware-bundle-import",
        },
        "deployment_id": event.get("deployment_id"),
        "capabilities": ["camera", "sd_fatfs", "event_artifact"],
        "status": "active",
        "created_at": created_at,
        "last_seen_at": event.get("timestamp"),
        "metadata": {
            "auto_registered": True,
            "import_source": "firmware_bundle",
        },
    }


def _resolve_media_paths(
    event: dict[str, Any],
    bundle_root: Path,
    destination_media_dir: Path | None,
    copy_media: bool,
    result: FirmwareBundleImportResult,
) -> dict[str, Any]:
    updated = json.loads(json.dumps(event))
    for media in updated.get("media", []):
        original_path = media.get("path")
        if not original_path:
            continue
        source_path = _media_source_path(bundle_root, Path(original_path))
        if copy_media:
            if destination_media_dir is None:
                raise ValueError("destination media directory is required when copy_media=True")
            destination = destination_media_dir / source_path.name
            if source_path.exists():
                shutil.copy2(source_path, destination)
                media["path"] = str(destination)
                result.copied_media.append(str(destination))
            else:
                media["path"] = str(source_path)
                result.referenced_media.append(str(source_path))
        else:
            media["path"] = str(source_path)
            result.referenced_media.append(str(source_path))
    return updated


def _media_source_path(bundle_root: Path, media_path: Path) -> Path:
    if media_path.is_absolute():
        return media_path
    if len(media_path.parts) >= 2 and media_path.parts[0] == "sdcard":
        return bundle_root.joinpath(*media_path.parts[1:])
    if len(media_path.parts) >= 2 and media_path.parts[0] == "media":
        return bundle_root / media_path
    if media_path.parent == Path("."):
        return bundle_root / "media" / media_path.name
    return bundle_root / media_path
