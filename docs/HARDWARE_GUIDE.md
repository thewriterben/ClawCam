# ClawCam Hardware Guide

ClawCam will support hardware in tiers. The first release should target one recommended node board and one recommended gateway class before expanding compatibility.

## Hardware Tiers

| Tier | Hardware Class | Use Case | Status |
|---|---|---|---|
| **Tier A: MVP Node** | ESP32-S3 camera board with PSRAM and SD support | Low-cost field camera trap | Planned |
| **Tier B: Agentic Node** | ESP32-S3/P4 board compatible with ESP-Claw board manager | On-device event router, Lua rules, capabilities, and optional lightweight inference | Planned |
| **Tier C: Gateway** | Raspberry Pi 5, Jetson Orin Nano, or mini PC | Multi-node ingest, local storage, AI inference, dashboard, and MCP/MQTT server | Planned |
| **Tier D: Brain Host** | Desktop/server/cloud host running Oh-Ben-Claw adapter | Fleet reasoning, reports, and multi-agent operations | Planned |

## Initial Node Requirements

The first ClawCam node should include an ESP32-S3-class MCU, PSRAM, camera connector/module, local storage, battery measurement, a PIR or equivalent trigger input, and power-management support. Optional GPS, BME280/BMP280, light sensing, and LoRa should be added only after the baseline capture flow works.

## Initial Gateway Requirements

The first gateway should run Linux, Python 3.11 or later, SQLite, and a local API service. If model inference is enabled, the gateway should have sufficient CPU/GPU/NPU resources for the selected model. Jetson-class devices are recommended for heavier image pipelines; Raspberry Pi-class devices are acceptable for ingest, storage, dashboard, and lighter inference.

## Power Strategy

Remote deployments must default to deterministic low-power behavior. Wi-Fi, model inference, LLM calls, and continuous networking must be explicitly enabled by profile and should be disabled automatically under low battery conditions.

## Day/Night Switching (IR-Cut Filter)

Optional, off by default, and not yet run on hardware. It is for an OV5640 module with a two-wire IR-cut filter fitted in place of the stock OV2640.

The filter is a bistable coil and its two wires must go to an H-bridge, not to GPIOs. A DRV8833 breakout is recommended: its inputs have pull-downs, so the coil stays off during boot and deep sleep. Wire AOUT1/AOUT2 to the filter, VM to 5 V, nSLEEP high, grounds common, and AIN1/AIN2 to two free GPIOs. Set those in `CONFIG_CLAWCAM_IRCUT_GPIO_A` and `CONFIG_CLAWCAM_IRCUT_GPIO_B` (menu "ClawCam Camera"). The ESP32-S3-EYE leaves almost no GPIO free, so check its schematic first.

On a cold boot the node pulses the filter in (day). On every wake it reads scene light from the OV5640 (average level divided by gain and exposure, logged as `light=`), and after `CONFIG_CLAWCAM_DAY_NIGHT_DWELL` consecutive wakes below `NIGHT_BELOW` it pulses the filter out; above `DAY_ABOVE` it goes back. The filter and the record of its position both persist through deep sleep. The two thresholds are estimates: read `light=` from the log at dusk and in the dark and replace them. If day and night come out swapped, flip `CONFIG_CLAWCAM_IRCUT_ENGAGE_ON_A` or swap the filter wires.

## Expansion Policy

New boards should not be listed as supported until they have a documented wiring profile, build configuration, and at least one successful capture-and-ingest test.
