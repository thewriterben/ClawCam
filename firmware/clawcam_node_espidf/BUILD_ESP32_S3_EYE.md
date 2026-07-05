# ClawCam ESP32-S3-EYE Build Profile

This document defines the first ClawCam ESP-IDF build profile for the ESP32-S3-EYE v2.2 camera target. The profile is intended for bench validation of the camera initialization and one-frame JPEG capture path.

## Current Status

The ESP32-S3-EYE profile is **hardware-specific but unverified**. The firmware contains a gated `esp32-camera` path and a boot-time camera smoke test, but the board must not be described as supported until the build, flash, camera capture, storage, and wake behavior are tested on physical hardware.

## Prerequisites

Use a working ESP-IDF environment with the `idf.py` command available. The ClawCam camera component declares an optional `espressif/esp32-camera` dependency that is used when `CONFIG_CLAWCAM_CAMERA_USE_ESP_CAMERA=y`.

## Build Command

From this directory:

```bash
idf.py -D SDKCONFIG_DEFAULTS=sdkconfig.defaults.esp32s3_eye set-target esp32s3 build
```

## Flash and Monitor

Replace the serial port with the port for your board.

```bash
idf.py -p /dev/ttyACM0 flash monitor
```

## Expected Smoke-Test Behavior

When `CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT=y`, the firmware should initialize the ESP32-S3-EYE camera pin map, attempt one JPEG capture, log the captured frame length and dimensions, and release the framebuffer. If `CONFIG_CLAWCAM_STORAGE_PERSIST_SMOKE_TEST_CAPTURE=y`, a successful capture is also written to `/sdcard/media`, paired smoke-test metadata is written to `/sdcard/metadata`, and a gateway-ingestible `clawcam.event.v1`-shape event artifact is written to `/sdcard/events`. If `CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED=y`, the firmware also attempts to register the bench node and POST the generated event JSON to the gateway API. SD-card artifacts remain the offline source of truth; upload failure is logged but does not delete or alter local artifacts. If the camera, storage, or gateway client path is disabled or unavailable, the firmware logs the failure and uses `ESP_ERR_NOT_SUPPORTED` or a concrete ESP-IDF error rather than pretending success.

## Promotion Criteria

| Step | Required Result |
|---|---|
| Build | `idf.py ... build` completes with the ESP32-S3-EYE defaults. |
| Flash | Firmware flashes and logs boot messages on the physical board. |
| Camera init | `esp_camera_init()` returns `ESP_OK`. |
| Capture | `esp_camera_fb_get()` returns a non-empty JPEG frame. |
| Release | `clawcam_camera_release()` returns the framebuffer without a crash. |
| Storage mount | SD/FATFS mounts at `/sdcard` without formatting unless formatting was explicitly enabled for bench testing. |
| Media persistence | Captured JPEG is saved under `/sdcard/media`. |
| Metadata persistence | JSON metadata is saved under `/sdcard/metadata`. |
| Event artifact | Gateway-compatible event JSON is saved under `/sdcard/events`. |
| Optional upload | If enabled, firmware registers the node via `/api/v1/devices` and uploads the event via `/api/v1/events`. |
| Wi-Fi | Station bring-up is implemented behind `CONFIG_CLAWCAM_WIFI_ENABLED` (set `CLAWCAM_WIFI_SSID` / `CLAWCAM_WIFI_PASSWORD` in menuconfig). Without it, gateway upload/OTA/MQTT cannot reach the network. |
| Gateway auth | Set `CLAWCAM_GATEWAY_API_TOKEN` in menuconfig when the gateway runs with auth enabled; sent as a Bearer header on all HTTP calls. |
| Telemetry | Each wake cycle POSTs a schema-valid health report (battery when `CLAWCAM_BATTERY_ADC_CHANNEL` >= 0, storage when SD mounted) and uploads the JPEG to `/api/v1/media/{event_id}`, which is what triggers gateway inference/alerts/cloud sync. |
| Storage policy | `min_free_bytes` is enforced before media writes; optional oldest-first auto-cleanup (`auto_cleanup_enabled`, max 16 deletions/wake). |
| Next port | Field-validate Wi-Fi + upload on real hardware; add provisioning (softAP/BLE) for non-hardcoded credentials. |

## References

[1]: https://github.com/espressif/esp-who/blob/master/docs/en/get-started/ESP32-S3-EYE_Getting_Started_Guide.md "Espressif ESP32-S3-EYE Getting Started Guide"
[2]: https://github.com/espressif/esp32-camera "Espressif esp32-camera driver"
