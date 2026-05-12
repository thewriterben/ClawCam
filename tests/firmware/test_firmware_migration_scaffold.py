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


def test_esp32_s3_eye_profile_defines_concrete_camera_pins_but_remains_unverified() -> None:
    profile_path = ROOT / "firmware/clawcam_node_espidf/boards/esp32_s3_eye_v22.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["board_id"] == "esp32-s3-eye-v2.2"
    assert profile["status"] == "initial_target_pinmap_unverified"
    pins = profile["camera"]["pins"]
    assert pins["xclk"] == 15
    assert pins["d0"] == 11
    assert pins["d7"] == 16
    assert pins["vsync"] == 6
    assert pins["href"] == 7
    assert pins["pclk"] == 13
    assert profile["storage"]["pins"]["d0"] == 40
    assert any("captures a valid JPEG" in requirement for requirement in profile["promotion_requirements"])


def test_camera_component_exposes_esp32_camera_integration_gate() -> None:
    camera_source = (ROOT / "firmware/clawcam_node_espidf/components/clawcam_camera/clawcam_camera.c").read_text(encoding="utf-8")
    camera_header = (ROOT / "firmware/clawcam_node_espidf/components/clawcam_camera/include/clawcam_camera.h").read_text(encoding="utf-8")
    kconfig = (ROOT / "firmware/clawcam_node_espidf/components/clawcam_camera/Kconfig").read_text(encoding="utf-8")
    assert "CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA" in camera_source
    assert "esp_camera_init" in camera_source
    assert "esp_camera_fb_get" in camera_source
    assert "clawcam_camera_default_esp32_s3_eye_config" in camera_header
    assert "CLAWCAM_CAMERA_USE_ESP_CAMERA" in kconfig
    assert "CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT" in kconfig
    assert "CLAWCAM_CAMERA_SMOKE_TEST_RETRY_COUNT" in kconfig


def test_esp32_s3_eye_build_defaults_enable_hardware_smoke_test_profile() -> None:
    defaults = (ROOT / "firmware/clawcam_node_espidf/sdkconfig.defaults.esp32s3_eye").read_text(encoding="utf-8")
    assert 'CONFIG_IDF_TARGET="esp32s3"' in defaults
    assert "CONFIG_SPIRAM=y" in defaults
    assert "CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA=y" in defaults
    assert "CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT=y" in defaults


def test_firmware_main_contains_safe_capture_smoke_test_flow() -> None:
    main_source = (ROOT / "firmware/clawcam_node_espidf/main/main.c").read_text(encoding="utf-8")
    assert "run_camera_smoke_test" in main_source
    assert "clawcam_camera_capture(&capture)" in main_source
    assert "camera smoke test passed" in main_source
    assert "clawcam_camera_release(&capture)" in main_source
    assert "CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT" in main_source


def test_oh_ben_claw_example_config_documents_stdio_bridge() -> None:
    config = (ROOT / "brain/oh-ben-claw-adapter/examples/clawcam-mcp-stdio.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.clawcam_gateway]" in config
    assert 'transport = "stdio"' in config
    assert "clawcam_gateway.mcp_server.stdio_server" in config
    assert "get_recent_detections" in config
    assert "apply_config_patch" in config
