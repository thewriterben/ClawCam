# ClawCam

**ClawCam** is a smart camera platform that combines resilient ESP32 camera-trap hardware, an offline-first field gateway, and an edge AI operations layer. Wildlife monitoring is its first profile; device profiles also cover home security, bird feeders, livestock, apiaries, gardens, and driveways.

## Current Progress
> **Current Status**: Phase 12 complete (software, simulator-verified); next milestone is physical hardware integration. See the [roadmap](docs/ROADMAP.md) and [detailed status](docs/STATUS.md).

### Phased Development Roadmap
ClawCam’s development is intentionally phased to ensure each milestone delivers a functional, testable increment before advancing:

- **Phase 0 — Repository Foundation** ✅ Monorepo, docs, JSON schemas.
- **Phase 1 — Working Vertical Slice** ✅ Simulator → gateway ingest → MCP stdio bridge → Oh-Ben-Claw brain adapter, end to end.
- **Phase 2 — Command Transport & Persistent Config** ✅ Command poll/ack loop, capability groups, NVS-backed firmware config.
- **Phase 3 — Real-Time Transport & AI Inference** ✅ MegaDetector inference pipeline (3A), MQTT bridge + firmware client (3B), OTA firmware updates (3C).
- **Phase 4 — Cloud Storage Backend** ✅ S3/GCS/Noop stores; auto-upload with tracking; offline-first preserved.
- **Phase 5 — Data Export & Dashboard** ✅ CSV exports, cloud upload retry, enriched operator dashboard.
- **Phase 6 — Alert Rules & Webhooks** ✅ Persistent alert rules; webhook delivery; alert audit trail.
- **Phase 7 — Multi-Tenant Foundation** ✅ Deployments, API key auth with ordered scopes.
- **Phase 8 — Device Profiles & States** ✅ 10 device profiles with behavioral defaults; runtime states (armed, away, feeding…) with audit trail.
- **Phase 9 — Schedule Engine** ✅ Cron-driven persistent scheduled actions (set state, toggle rules, webhooks).
- **Phase 10 — Detection Zones & Privacy Masks** ✅ Normalised polygon zones; alert/record/ignore/privacy_mask actions.
- **Phase 11 — Audio Pipeline** ✅ Audio capture, BirdNET/mock classification, storage, and tools.
- **Phase 12 — Multi-Detector Orchestration** ✅ Detector registry with lazy loading; per-profile/per-device detector chains.

## Project Status at a Glance
- Repository Skeleton: **Working**
- JSON Schemas: **Working**
- Node Simulator: **Working**
- Gateway Service: **Working** (FastAPI + SQLite; auth, inference, MQTT, OTA, alerts, schedules, zones, audio)
- Firmware (ESP-IDF): **Working in simulation** (capture loop, deep sleep, command client, MQTT, OTA — pending field validation on hardware)
- Brain Integration: **Working** (ClawCamAdapter: MCP stdio bridge, 23 auto-approved read tools, 9 approval-gated write tools)
- Cloud Backend: **Working** (optional; S3/GCS; disabled by default)

*For a more detailed view on progress tracking and milestones, check the [STATUS.md](docs/STATUS.md).*

#### Ground Rules:
- No feature will be described as "Production-ready" until verified with tests and reproducible steps.

### Next Milestone: Production Hardening (Phase 13)
All software phases are simulator-verified. Phase 13 hardens them — MCP 2026-07-28 readiness, an evaluation harness as CI release gate, gateway observability, and a scoped approval model — executed in lockstep with Oh-Ben-Claw Phase 15 (see `NEXT_PHASE_PLAN.md`). Hardware integration (physical ESP32-S3-EYE field test) follows as Phase 14.

---

## Getting Started

### Requirements:
1. Python installed with FastAPI.
2. SQLite3 for database; Python scripts assume SQLite persistence.

### Steps to Launch Gateway:
```bash
cd gateway
python -m clawcam_gateway.main
```

### Workflows:
- **Simulator**: Generate event payloads without node hardware:
   ```bash
   python -m clawcam_gateway.simulator.cli
   ```

---

## Project Overview and Structure
### ClawCam Architecture
ClawCam is built around three primary operational layers:
1. **ClawCam Node**: Powered by ESP32 boards for motion-triggered capture and local storage.
2. **ClawCam Gateway**: Offline-first field station running on Raspberry Pi or similar.
3. **ClawCam Brain**: [Oh-Ben-Claw](https://github.com/thewriterben/Oh-Ben-Claw) agent consuming gateway tools via the MCP stdio bridge (`brain/oh-ben-claw-adapter/`), with read-only tools auto-approved and world-changing tools approval-gated.

### Repository Layout
```plaintext
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
└── legacy_archives/              # Original imported archives retained for reference only
```

### Design Principles
1. **Field Reliability First**: Operate smoothly in constrained environments.
2. **Agentic Intelligence Second**: Enhance node to gateway interactions using AI agents.
3. **Cloud Scale as a Bonus**: Decentralized systems are prioritized.

*Detailed architecture vision can be found in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).*

---

For additional references on upcoming phases and detailed milestones, visit:
- [Roadmap (docs/ROADMAP.md)](docs/ROADMAP.md)
- [Status Details (docs/STATUS.md)](docs/STATUS.md)