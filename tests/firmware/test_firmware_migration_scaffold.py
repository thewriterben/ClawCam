from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]


def test_wildcam_migration_document_names_core_components() -> None:
    text = (ROOT / "firmware/clawcam_node_espidf/MIGRATION_FROM_WILDCAM.md").read_text(encoding="utf-8")
    for component in [
        "clawcam_camera",
        "clawcam_motion",
        "clawcam_storage",
        "clawcam_power",
    ]:
        assert component in text
    for source in ["CameraManager", "MotionDetector", "StorageManager", "PowerManager"]:
        assert source in text


def test_firmware_component_headers_define_expected_public_apis() -> None:
    expected = {
        "clawcam_camera": ["clawcam_camera_init", "clawcam_camera_capture", "clawcam_camera_release"],
        "clawcam_motion": ["clawcam_motion_init", "clawcam_motion_is_detected", "clawcam_motion_get_event"],
        "clawcam_storage": ["clawcam_storage_init", "clawcam_storage_save_media", "clawcam_storage_get_health"],
        "clawcam_power": ["clawcam_power_init", "clawcam_power_get_state", "clawcam_power_enter_deep_sleep"],
    }
    for component, symbols in expected.items():
        header = ROOT / f"firmware/clawcam_node_espidf/components/{component}/include/{component}.h"
        assert header.exists(), f"missing header: {header}"
        text = header.read_text(encoding="utf-8")
        for symbol in symbols:
            assert symbol in text


def test_reference_board_profile_remains_explicitly_not_supported() -> None:
    profile_path = ROOT / "firmware/clawcam_node_espidf/boards/esp32_s3_camera_reference.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["board_id"] == "esp32-s3-camera-reference"
    assert profile["status"] == "planned_pinmap"
    assert any("not a supported hardware profile" in note for note in profile["notes"])


def test_oh_ben_claw_example_config_documents_stdio_bridge() -> None:
    config = (ROOT / "brain/oh-ben-claw-adapter/examples/clawcam-mcp-stdio.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.clawcam_gateway]" in config
    assert 'transport = "stdio"' in config
    assert "clawcam_gateway.mcp_server.stdio_server" in config
    assert "get_recent_detections" in config
    assert "apply_config_patch" in config
