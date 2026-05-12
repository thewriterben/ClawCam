# ClawCam Node ESP-IDF Firmware

This directory will contain the next-generation ClawCam field node firmware. It is intentionally structured as ESP-IDF components so WildCAM camera-trap behavior can be migrated cleanly and ESP-Claw capability groups can be added without turning the firmware into a monolithic sketch.

## Component Plan

| Component | Purpose |
|---|---|
| `clawcam_camera` | Camera initialization, capture, flash/IR control, frame metadata. |
| `clawcam_motion` | PIR and other event-trigger sources. |
| `clawcam_power` | Battery measurement, power profiles, deep sleep, solar/charger signals. |
| `clawcam_storage` | Local media and JSON metadata storage. |
| `clawcam_sensors` | Environmental, GPS, light, and optional external sensors. |
| `clawcam_events` | Event creation, queueing, serialization, and gateway publication. |
| `clawcam_capabilities` | ESP-Claw-compatible wildlife capability group surface. |

## First Firmware Milestone

The first milestone is not full ESP-Claw integration. The first milestone is deterministic camera-trap behavior: boot, read config, capture on trigger, save media and metadata, emit an event summary, and sleep safely.

## Initial Camera Target

The first concrete board target is `boards/esp32_s3_eye_v22.json`. It provides a hardware-specific but unverified ESP32-S3-EYE v2.2 pin map derived from Espressif BSP definitions. The `clawcam_camera` component now exposes `clawcam_camera_default_esp32_s3_eye_config()` and an optional `CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA` hardware path that calls `esp_camera_init()` and `esp_camera_fb_get()` when the `esp32-camera` component is available.

The hardware path is intentionally gated. When the option is disabled or the driver is unavailable, the camera component remains scaffold-safe and `clawcam_camera_capture()` returns `ESP_ERR_NOT_SUPPORTED` rather than pretending capture is implemented.

Use `BUILD_ESP32_S3_EYE.md` and `sdkconfig.defaults.esp32s3_eye` for the first bench build. That profile enables PSRAM, the gated `esp32-camera` path, and `CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT`, which performs one safe capture attempt, logs JPEG frame details, and releases the framebuffer.

## ESP-Claw Integration Direction

Once the deterministic baseline works, this firmware should add ESP-Claw-style event routing, Lua deterministic rules, local memory, and MCP/capability exposure for safe wildlife-specific operations.
