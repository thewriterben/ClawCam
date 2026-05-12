# ClawCam Board Profiles

This directory contains hardware board profiles for the ClawCam ESP-IDF node firmware. A board profile is not the same as a supported deployment target. A board becomes supported only after build, flash, capture, storage, power, and wake tests pass on physical hardware.

## Initial Target

The initial concrete camera target is `esp32_s3_eye_v22.json`. The ESP32-S3-EYE v2.2 is a practical first firmware-port target because Espressif documents it as an ESP32-S3 AI development board with an OV2640 2-megapixel camera, 8 MB Octal PSRAM, 8 MB flash, a MicroSD slot, and optional battery pads. The pin map in this profile is derived from Espressif BSP definitions for `esp32_s3_eye`.

| Profile | Status | Purpose |
|---|---|---|
| `esp32_s3_eye_v22.json` | `initial_target_pinmap_unverified` | First hardware-ready camera-profile target for ESP-IDF camera initialization work. |
| `esp32_s3_camera_reference.json` | `planned_pinmap` | Generic placeholder retained for future board-selection work. |

## Promotion Rules

A profile may be promoted to `supported` only after the firmware builds for the board, camera initialization succeeds, a JPEG capture is produced, the image is stored on local media, metadata is generated, and power/wake behavior is tested.

## References

[1]: https://github.com/espressif/esp-who/blob/master/docs/en/get-started/ESP32-S3-EYE_Getting_Started_Guide.md "Espressif ESP32-S3-EYE Getting Started Guide"
[2]: https://raw.githubusercontent.com/espressif/esp-bsp/master/bsp/esp32_s3_eye/include/bsp/esp32_s3_eye.h "Espressif ESP-BSP esp32_s3_eye.h"
