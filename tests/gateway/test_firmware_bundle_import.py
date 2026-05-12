from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from clawcam_gateway.ingest.firmware_bundle import import_firmware_bundle
from clawcam_gateway.storage.database import GatewayDatabase


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_BUNDLE = ROOT / "samples" / "firmware-bundle"


def test_import_firmware_bundle_auto_registers_device_and_copies_media(tmp_path) -> None:
    db = GatewayDatabase(tmp_path / "gateway.db")
    media_dir = tmp_path / "media"

    result = import_firmware_bundle(SAMPLE_BUNDLE, db, media_dir=media_dir, copy_media=True)

    assert result.imported_events == ["evt-smoke-123"]
    assert result.registered_devices == ["esp32-s3-eye-v2.2-bench-node"]
    assert len(result.copied_media) == 1
    copied_media = Path(result.copied_media[0])
    assert copied_media.exists()
    assert copied_media.parent == media_dir

    device = db.get_device("esp32-s3-eye-v2.2-bench-node")
    assert device is not None
    assert device["device_type"] == "node"
    assert device["hardware"]["board"] == "esp32-s3-eye-v2.2"

    events = db.recent_events(limit=5)
    assert len(events) == 1
    assert events[0]["event_id"] == "evt-smoke-123"
    assert events[0]["media"][0]["path"] == str(copied_media)


def test_import_firmware_bundle_can_reference_media_in_place(tmp_path) -> None:
    db = GatewayDatabase(tmp_path / "gateway.db")

    result = import_firmware_bundle(SAMPLE_BUNDLE, db, copy_media=False)

    assert result.imported_events == ["evt-smoke-123"]
    assert result.copied_media == []
    assert len(result.referenced_media) == 1
    assert result.referenced_media[0].endswith("samples/firmware-bundle/media/smoke-123.jpg")
    event = db.recent_events(limit=1)[0]
    assert event["media"][0]["path"].endswith("samples/firmware-bundle/media/smoke-123.jpg")


def test_import_firmware_bundle_cli(tmp_path) -> None:
    db_path = tmp_path / "gateway.db"
    media_dir = tmp_path / "gateway_media"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "clawcam_gateway.ingest.cli",
            "import-firmware-bundle",
            str(SAMPLE_BUNDLE),
            "--db",
            str(db_path),
            "--media-dir",
            str(media_dir),
        ],
        cwd=ROOT / "gateway",
        env={"PYTHONPATH": str(ROOT / "gateway")},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "registered device:esp32-s3-eye-v2.2-bench-node" in completed.stdout
    assert "imported event:evt-smoke-123" in completed.stdout
    assert "summary events=1 media=1 devices=1" in completed.stdout
    assert (media_dir / "smoke-123.jpg").exists()
