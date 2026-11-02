# ClawCam Board Profiles

This directory contains hardware board profiles for the ClawCam ESP-IDF node firmware. A board profile is not the same as a supported deployment target. A board becomes supported only after build, flash, capture, storage, power, and wake tests pass on physical hardware.

## Initial Target

The initial concrete camera target is `esp32_s3_eye_v22.json`. The ESP32-S3-EYE v2.2 is a practical first firmware-port target because Espressif documents it as an ESP32-S3 AI development board with an OV2640 2-megapixel camera, 8 MB Octal PSRAM, 8 MB flash, a MicroSD slot, and optional battery pads. The pin map in this profile is derived from Espressif BSP definitions for `esp32_s3_eye`.

| Profile | Status | Purpose |
|---|---|---|
| `esp32_s3_eye_v22.json` | `initial_target_pinmap_unverified` | First hardware-ready camera-profile target for ESP-IDF camera initialization work. |
| `esp32_s3_camera_reference.json` | `planned_pinmap` | Generic placeholder retained for future board-selection work. |
| `emakefun_esp32_s3_cam.json` | `vendor_pinmap_unverified` | nulllab/emakefun ESP32-S3-CAM, on the bench 2026-11-01. Vendor-stated pins, ESP32-S3-EYE map. |
| `esp32_s3_wroom_cam.json` | `vendor_pinmap_unverified` | ESP32-S3-WROOM-1 CAM board (maker unnamed), on the bench 2026-11-01. Seller-stated pins, ESP32-S3-EYE map. |

## Boards Added 2026-11-01

Both new boards wire the camera and SD card exactly as the ESP32-S3-EYE does (XCLK 15, SIOD 4, SIOC 5, VSYNC 6, HREF 7, PCLK 13, D0-D7 11/9/8/10/12/18/17/16, SD CMD 38 / CLK 39 / D0 40), so the firmware's existing `clawcam_camera_default_esp32_s3_eye_config` already drives them. Two things differ from the EYE and are unchecked: image orientation (the EYE sets `vflip`; these profiles do not until a capture shows which way up the sensor sits) and the sensor fitted, which varies by listing (`sensor_options`). `vendor_pinmap_unverified` means the pins come from the vendor's or seller's own documents, not from a capture on our hardware.

- **nulllab/emakefun ESP32-S3-CAM** — ESP32-S3R8 (8 MB octal PSRAM), 8 MB flash, OV2640 or OV3660, flash LED on GPIO3, PH2.0 battery input with charger, native USB only. Source: [nulllab esp32s3-cam README][3].
- **ESP32-S3-WROOM-1 CAM** — WROOM-1 module with octal PSRAM (GPIO35-37 reserved), OV2640 or OV5640, LED on GPIO2, WS2812 on GPIO48, a second USB-C through a USB-UART bridge on GPIO43/44. Source: the seller's listing, which names no maker or URL.

### Loose OV5640 module

A separate OV5640 module is on the bench too: 5 MP, autofocus-capable sensor on a 24-pin DVP FPC of roughly 100 mm, sold with several lens options. It fits either board's camera socket. esp32-camera identifies it by PID (0x5640, SCCB address 0x3C) and needs no pin change. The long FPC is the risk: if frames tear or overflow at 16 MHz XCLK, lower `xclk_hz` first. JPEG at full 2592x1944 needs the octal PSRAM both boards have.

## Promotion Rules

A profile may be promoted to `supported` only after the firmware builds for the board, camera initialization succeeds, a JPEG capture is produced, the image is stored on local media, metadata is generated, and power/wake behavior is tested.

## References

[1]: https://github.com/espressif/esp-who/blob/master/docs/en/get-started/ESP32-S3-EYE_Getting_Started_Guide.md "Espressif ESP32-S3-EYE Getting Started Guide"
[2]: https://raw.githubusercontent.com/espressif/esp-bsp/master/bsp/esp32_s3_eye/include/bsp/esp32_s3_eye.h "Espressif ESP-BSP esp32_s3_eye.h"
[3]: https://github.com/nulllaborg/esp32s3-cam "nulllab esp32s3-cam README"
