# ClawCam Status

This document is the source of truth for current implementation maturity. ClawCam tracks progress for **working code**, **scaffolds**, **frameworks**, and **planned features**.

## Current Repository State (Phase 1 Complete)

| Area                       | Status             | Notes                                                                                |
|----------------------------|--------------------|--------------------------------------------------------------------------------------|
| Repository skeleton        | ✅ **Working**      | Monorepo layout established for modular development.                                 |
| JSON schemas               | ✅ **Working**      | Validation tests for device, event, health, observation contracts.                   |
| Node simulator             | ✅ **Working**      | Deterministic simulator generates schema-compatible payloads.                        |
| Gateway service            | ✅ **Working**      | FastAPI + SQLite; ingest, read tools, approval-gated command queue, dashboard.       |
| Gateway MCP stdio bridge   | ✅ **Working**      | JSON-RPC stdio bridge; initialize, tools/list, tools/call, ping.                    |
| Approval-gated tools       | ✅ **Working**      | capture_now and apply_config_patch queue pending commands; policy enforced.          |
| Firmware capture loop      | ✅ **Working**      | Deterministic PIR → capture → deep sleep; RTC timestamp; component-based ESP-IDF.   |
| Firmware deep sleep        | ✅ **Working**      | EXT0 PIR wake + timer fallback; battery-aware extended sleep.                        |
| Brain adapter              | ✅ **Working**      | ClawCamAdapter: subprocess stdio, tool discovery, approval policy, OBC registration. |
| End-to-end Phase 1 tests   | ✅ **Working**      | Five-layer integration test: simulator → DB → Python tools → MCP → brain adapter.   |
| Cloud backend              | 🔲 **Planned**      | Deferred until local system achieves MVP with real hardware.                         |
| MQTT bridge                | 🔲 **Planned**      | Phase 3; gateway ↔ node and Oh-Ben-Claw spine.                                       |
| AI model inference         | 🔲 **Planned**      | Phase 3; SpeciesNet / MegaDetector pipeline in gateway.                              |
| ESP-Claw capability groups | 🔲 **Planned**      | Phase 2; capability routing and node command transport.                              |

Ground Rules:
- No feature will be described as "Working" until verified with tests and reproducible steps.

## Phase 1 Complete — Vertical Slice

Phase 1 delivers a complete offline-first development loop without physical hardware:

1. **Simulator** generates schema-valid device/event/health payloads.
2. **Gateway** ingests, validates, and stores them in SQLite.
3. **Read-only tools** (get_recent_detections, get_node_health, generate_daily_summary, list_pending_commands) query the database and return structured results.
4. **Approval-gated tools** (capture_now, apply_config_patch) queue pending commands with audit trails; nodes poll the queue in Phase 2.
5. **MCP stdio bridge** exposes all tools via JSON-RPC so any MCP-compatible client can connect.
6. **Brain adapter** (ClawCamAdapter) launches the bridge as a subprocess, discovers tools, enforces the approval policy, and provides an Oh-Ben-Claw registration helper.
7. **Firmware** runs a deterministic PIR → capture → deep sleep loop on ESP32-S3-EYE with real timestamp support and battery-aware sleep scheduling.

## Next Milestone (Phase 2): ESP-Claw Native Node

- Node command transport: nodes poll /api/v1/commands/{device_id}/pending on each wake
- ESP-Claw capability groups for standardized tool interfaces
- Node announces capabilities via MQTT and responds to tool-call topics
- Approval-gated commands flow from brain → gateway queue → node on wake

---