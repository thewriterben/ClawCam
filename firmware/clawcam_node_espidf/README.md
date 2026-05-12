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

## ESP-Claw Integration Direction

Once the deterministic baseline works, this firmware should add ESP-Claw-style event routing, Lua deterministic rules, local memory, and MCP/capability exposure for safe wildlife-specific operations.
