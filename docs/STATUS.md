# ClawCam Status

This document is the source of truth for current implementation maturity. ClawCam intentionally distinguishes **working code**, **scaffolds**, **frameworks**, and **planned features**.

## Status Legend

| Status | Meaning |
|---|---|
| **Working** | Implemented in this repository and testable from documented instructions. |
| **Scaffold** | Directory, API contract, schema, or placeholder exists, but runtime behavior is minimal. |
| **Framework** | Architecture and integration points are defined; implementation is not complete. |
| **Planned** | Roadmap item with no current implementation in this repository. |
| **Legacy Reference** | Preserved upstream archive or prior implementation used only as source material. |

## Current Repository State

| Area | Status | Notes |
|---|---|---|
| Repository skeleton | **Working** | Monorepo layout has been created. |
| Legacy archives | **Legacy Reference** | Original archives are retained under `legacy_archives/` and are not the active source of truth. |
| Documentation | **Scaffold** | Core docs are being created as implementation guides. |
| JSON schemas | **Scaffold** | Initial schema files define device, event, observation, and health contracts. |
| Gateway service | **Scaffold** | Python package layout, API, SQLite persistence, schema validation, sample import CLI, first MCP-style tool functions, HTTP tool dispatch, dashboard JSON, and a minimal local HTML dashboard exist. Runtime is still local-development grade. |
| Node simulator | **Working** | Deterministic simulator can generate schema-compatible device, event, and health payloads without hardware. |
| Firmware | **Scaffold** | ESP-IDF component layout exists, WildCAM migration interfaces are defined, ESP32-S3-EYE is selected as the first unverified camera target, and the camera component now has a gated `esp32-camera` hardware path plus ESP32-S3-EYE build defaults and a boot-time capture smoke test. Physical hardware validation is still required. |
| Brain adapter | **Scaffold** | Oh-Ben-Claw/MCP tool definitions are being staged; Python tool functions, HTTP tool dispatch, and a lightweight MCP-compatible stdio bridge exist for recent detections, node health, and daily summary. |
| AI model integration | **Planned** | SpeciesNet, MegaDetector-style detection, ESP-DL, and LiteRT integrations are planned but not implemented here yet. |
| Cloud backend | **Planned** | Cloud is intentionally deferred until the local field system works. |

## Ground Rules

ClawCam will not describe features as production-ready until they have implementation, tests, and documented reproduction steps. Advanced features such as LoRa mesh, satellite communication, federated learning, multi-agent collaboration, and cloud dashboards are valid roadmap items, but they remain **Planned** until concrete code and tests exist in this repository.

## First Milestone Definition

The first milestone is substantially implemented for a simulator-based development loop: a simulator can generate payloads, sample payloads exist, the gateway can validate and persist events, Python and HTTP tool functions can query recent detections and node health, and a minimal local dashboard can render the gateway state. It is complete only when the same flow includes a real hardware node path and documented release-grade setup instructions.
