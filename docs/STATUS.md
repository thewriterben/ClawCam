# ClawCam Status

This document is the source of truth for current implementation maturity. ClawCam tracks progress for **working code**, **scaffolds**, **frameworks**, and **planned features**.

## Current Repository State

| Area                    | Status                | Notes                                                                 |
|-------------------------|-----------------------|-----------------------------------------------------------------------|
| Repository skeleton     | ✅ **Working**         | Monorepo layout established for modular development.                  |
| JSON schemas            | ✅ **Working**         | Validation tests added for device and event contracts.                |
| Node simulator          | ✅ **Working**         | Deterministic simulator generates schema-compatible payloads.         |
| Gateway service         | 🔄 **In Progress**     | Local FastAPI gateway under testing; SQLite persistence validated.    |
| Firmware (ESP-IDF)      | 🔄 **In Progress**     | Camera scaffolds prepared; field-ready deployment in development.     |
| Brain integration       | 🔲 **Planned**         | Oh-Ben-Claw/MCP tools partially defined; awaiting gateway completion. |
| Cloud backend           | 🔲 **Planned**         | Cloud postponed until local system achieves MVP status.               |

Ground Rules:
- No feature will be described as "Production-ready" until verified with tests and reproducible steps.

## First Milestone:
The first iteration targets a **simulator-based development loop**. Once real hardware is integrated, this milestone will close.

---