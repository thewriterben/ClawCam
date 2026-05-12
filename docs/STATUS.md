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
| Gateway service | **Scaffold** | Python package layout and intended module boundaries exist. Runtime implementation is next. |
| Firmware | **Scaffold** | ESP-IDF component layout exists. Hardware code is not yet ported. |
| Brain adapter | **Scaffold** | Oh-Ben-Claw/MCP tool definitions are being staged. |
| AI model integration | **Planned** | SpeciesNet, MegaDetector-style detection, ESP-DL, and LiteRT integrations are planned but not implemented here yet. |
| Cloud backend | **Planned** | Cloud is intentionally deferred until the local field system works. |

## Ground Rules

ClawCam will not describe features as production-ready until they have implementation, tests, and documented reproduction steps. Advanced features such as LoRa mesh, satellite communication, federated learning, multi-agent collaboration, and cloud dashboards are valid roadmap items, but they remain **Planned** until concrete code and tests exist in this repository.

## First Milestone Definition

The first milestone is a working vertical slice. It is complete only when a ClawCam node or simulator can submit an event to the gateway, the gateway validates the event against schema, persists it, exposes it through an API/tool interface, and a brain adapter can query recent detections.
