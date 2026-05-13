# ClawCam

**ClawCam** is a robust wildlife monitoring platform that combines resilient camera-trap hardware, a local field gateway, and an edge AI operations layer.

## Current Progress
> **Current Status**: In progress; [view roadmap](docs/ROADMAP.md) and [detailed status](docs/STATUS.md).

### Phased Development Roadmap
ClawCam’s development is intentionally phased to ensure each milestone delivers a functional, testable increment before advancing. Below is an overview of the current progress:

#### Phase 0: Repository Foundation (100% Complete)
- Monorepo skeleton established.
- Core documentation prepared: [STATUS.md](docs/STATUS.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md).
- Valid schema definitions for devices, events, observations, and health.

#### Phase 1: Working Vertical Slice (50% In Progress)
- Progress made on simulator event generation, gateway ingest, and API functionality.
- Brain tool and complete documentation remain planned for later iterations.

## Project Status at a Glance
- Repository Skeleton: **Working**
- JSON Schemas: **Working**
- Node Simulator: **Working**
- Gateway Service: **In Progress**
- Firmware (ESP-IDF): **In Progress**
- Brain Integration: **Planned**
- Cloud Backend: **Planned**

*For a more detailed view on progress tracking and milestones, check the [STATUS.md](docs/STATUS.md).*

---

## Detailed Status and Roadmap

### Current Repository State
| Area                    | Status                | Notes                                                                 |
|-------------------------|-----------------------|-----------------------------------------------------------------------|
| Repository skeleton     | ✅ **Working**         | Monorepo layout established for modular development.                  |
| JSON schemas            | ✅ **Working**         | Validation tests added for device and event contracts.                |
| Node simulator          | ✅ **Working**         | Deterministic simulator generates schema-compatible payloads.         |
| Gateway service         | 🔄 **In Progress**     | Local FastAPI gateway under testing; SQLite persistence validated.    |
| Firmware (ESP-IDF)      | 🔄 **In Progress**     | Camera scaffolds prepared; field-ready deployment in development.     |
| Brain integration       | 🔲 **Planned**         | Oh-Ben-Claw/MCP tools partially defined; awaiting gateway completion. |
| Cloud backend           | 🔲 **Planned**         | Cloud postponed until local system achieves MVP status.               |

#### Ground Rules:
- No feature will be described as "Production-ready" until verified with tests and reproducible steps.

### First Milestone:
The first iteration targets a **simulator-based development loop**. Once real hardware is integrated, this milestone will close.

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
3. **ClawCam Brain**: Centralized agent for fleet reasoning and task orchestration.

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