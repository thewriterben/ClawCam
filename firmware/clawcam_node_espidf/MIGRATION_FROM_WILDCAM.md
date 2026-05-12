# WildCAM to ClawCam ESP-IDF Firmware Migration Plan

ClawCam’s firmware direction is ESP-IDF component architecture. WildCAM_ESP32 remains the strongest source for deterministic camera-trap behavior, but its PlatformIO/Arduino-style classes should be ported deliberately into small C-compatible ESP-IDF components rather than copied as a monolithic application.

## Migration Principles

ClawCam firmware must remain deterministic before it becomes agentic. The first hardware milestone is boot, configure, detect motion, capture media, persist metadata, publish an event summary, and sleep safely. ESP-Claw-style capabilities and Lua rules should be layered above this baseline after the capture loop is stable.

## Source-to-Target Mapping

| WildCAM Source | ClawCam Component | First Port Target |
|---|---|---|
| `include/CameraManager.h`, `src/CameraManager.cpp`, `firmware/src/camera/*` | `components/clawcam_camera` | Camera init, capture, release framebuffer, quality/frame-size config, flash control. |
| `include/MotionDetector.h`, `src/MotionDetector.cpp` | `components/clawcam_motion` | PIR GPIO setup, debounce, wake-reason handling, motion event flag. |
| `include/StorageManager.h`, `src/StorageManager.cpp`, `firmware/core/storage_manager.*` | `components/clawcam_storage` | SD/FATFS mount, media write, metadata write, free-space health. |
| `include/PowerManager.h`, `src/PowerManager.cpp`, `firmware/power/*` | `components/clawcam_power` | Battery voltage/percentage, low-battery policy, wake sources, deep sleep. |
| `include/TimeManager.h`, `src/TimeManager.cpp` | Future `components/clawcam_time` or `clawcam_events` utility | RTC/NTP/GPS-aware event timestamps. |
| `include/SensorManager.h`, `src/SensorManager.cpp` | `components/clawcam_sensors` | Environmental, GPS, and light readings. |

## Minimum Capture Loop

The first port should produce this deterministic sequence:

```text
app_main
  → load static board/profile config
  → initialize power state
  → initialize storage
  → initialize camera
  → initialize motion trigger
  → if motion/manual/timer event:
       capture frame
       save image
       save event metadata
       emit event summary to serial/log/gateway queue
  → select sleep duration/profile
  → enter deep sleep
```

## API Design Direction

The new ESP-IDF components expose C APIs with explicit config and result structs. This keeps the code easy to test, easy to wrap for ESP-Claw capabilities, and independent from Arduino `String`/class patterns.

| Component | Header | Core Types |
|---|---|---|
| Camera | `clawcam_camera.h` | `clawcam_camera_config_t`, `clawcam_camera_capture_t` |
| Motion | `clawcam_motion.h` | `clawcam_motion_config_t`, `clawcam_motion_event_t` |
| Storage | `clawcam_storage.h` | `clawcam_storage_config_t`, `clawcam_storage_health_t` |
| Power | `clawcam_power.h` | `clawcam_power_config_t`, `clawcam_power_state_t`, `clawcam_power_profile_t` |

## Non-Goals for This Step

This migration prep does not yet implement board-specific camera pins, SDMMC wiring, battery ADC calibration, or real deep sleep behavior. It defines the stable component boundaries needed before porting hardware code.

## Immediate Next Firmware Task

The next firmware implementation task is to choose one supported ESP32-S3 camera board profile, add its pin map under `boards/`, and implement `clawcam_camera_init()` plus a stub-safe `clawcam_camera_capture()` path that can compile under ESP-IDF.
