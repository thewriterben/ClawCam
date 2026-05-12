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

## Expansion Policy

New boards should not be listed as supported until they have a documented wiring profile, build configuration, and at least one successful capture-and-ingest test.
