# ClawCam

**ClawCam** is an agentic wildlife monitoring platform that combines reliable camera-trap field hardware with an edge gateway and a claw-based AI operations layer.

ClawCam is the successor direction for the ideas explored in **WildCAM_ESP32**, **Oh-Ben-Claw**, and **ESP-Claw**. The goal is to build a practical, transparent, field-ready system rather than a collection of unverified feature claims.

> **Current status:** This repository is being rebuilt from a placeholder archive repository into a structured monorepo. The first milestone is a working vertical slice: one camera node, one local gateway, one schema-validated event flow, and one agent-compatible tool interface.

## Architecture

ClawCam is organized into three operational layers.

| Layer | Runtime | Responsibility |
|---|---|---|
| **ClawCam Node** | ESP32-S3 / ESP32-P4 / selected ESP32-CAM boards | Motion-triggered capture, local media and metadata storage, low-power operation, optional lightweight inference, and ESP-Claw-style local capabilities. |
| **ClawCam Gateway** | Raspberry Pi, Jetson, mini PC, or local server | Multi-node ingest, offline-first storage, dashboard/API, model inference, diagnostics, MQTT bridge, and MCP tools. |
| **ClawCam Brain** | Oh-Ben-Claw-compatible host or cloud agent | Fleet reasoning, natural-language operations, reporting, human-review workflows, maintenance planning, and multi-agent coordination. |

## Repository Layout

```text
ClawCam/
├── docs/                         # Architecture, status, hardware, data model, and standards docs
├── firmware/                     # ESP-IDF firmware and legacy migration notes
├── gateway/                      # Local field gateway service
├── brain/                        # Oh-Ben-Claw adapters, tools, agents, and examples
├── cloud/                        # Optional hosted backend and dashboard future work
├── models/                       # Model registry and edge/cloud inference notes
├── schemas/                      # JSON schemas for events, devices, observations, and health
├── skills/                       # Agentic workflows and Claw skills
├── tests/                        # Schema, gateway, firmware-interface, and integration tests
├── tools/                        # Repository automation and migration tools
└── legacy_archives/              # Original imported archives retained for reference only
```

## Design Principles

ClawCam prioritizes **field reliability first**, **agentic intelligence second**, and **cloud scale third**. A remote camera must be able to capture, save, sleep, and recover without relying on an LLM or continuous internet access.

The system uses deterministic embedded behavior for safety-critical and power-critical operations. Agentic workflows are layered above that base for configuration assistance, reporting, review triage, diagnostics, and fleet coordination.

## Immediate Roadmap

| Phase | Goal | Status |
|---|---|---|
| Phase 0 | Repository reset, docs, schemas, and CI | In progress |
| Phase 1 | Working node-to-gateway-to-agent vertical slice | Planned |
| Phase 2 | ESP-Claw-native wildlife node capability groups | Planned |
| Phase 3 | Gateway AI inference and human review workflow | Planned |
| Phase 4 | LoRa/MQTT field networking and offline sync | Planned |
| Phase 5 | Oh-Ben-Claw multi-agent ClawCam Brain | Planned |
| Phase 6 | Standards-aware cloud and research export | Planned |

## Start Here

Read these documents first:

| Document | Purpose |
|---|---|
| [`docs/STATUS.md`](docs/STATUS.md) | Honest implementation status and feature maturity. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Target system architecture and integration model. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phased implementation plan. |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Core records and schema strategy. |
| [`docs/AGENTIC_WORKFLOWS.md`](docs/AGENTIC_WORKFLOWS.md) | Agent roles, skills, tools, and approval boundaries. |

## License

License to be confirmed before first public release. Original upstream archives may contain their own licenses; retained archives are reference material only until code is intentionally migrated.
