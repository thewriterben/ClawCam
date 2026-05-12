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

When `CONFIG_CLAWCAM_CAMERA_SMOKE_TEST_ON_BOOT=y`, the firmware should initialize the ESP32-S3-EYE camera pin map, attempt one JPEG capture, log the captured frame length and dimensions, and release the framebuffer. If the camera driver is disabled or unavailable, capture should return `ESP_ERR_NOT_SUPPORTED` rather than pretending success.

## Promotion Criteria

| Step | Required Result |
|---|---|
| Build | `idf.py ... build` completes with the ESP32-S3-EYE defaults. |
| Flash | Firmware flashes and logs boot messages on the physical board. |
| Camera init | `esp_camera_init()` returns `ESP_OK`. |
| Capture | `esp_camera_fb_get()` returns a non-empty JPEG frame. |
| Release | `clawcam_camera_release()` returns the framebuffer without a crash. |
| Next port | Captured frame can be handed to storage once SD/FATFS is implemented. |

## References

[1]: https://github.com/espressif/esp-who/blob/master/docs/en/get-started/ESP32-S3-EYE_Getting_Started_Guide.md "Espressif ESP32-S3-EYE Getting Started Guide"
[2]: https://github.com/espressif/esp32-camera "Espressif esp32-camera driver"
