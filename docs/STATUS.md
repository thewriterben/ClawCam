# ClawCam Status

This document is the source of truth for current implementation maturity. ClawCam tracks progress for **working code**, **scaffolds**, **frameworks**, and **planned features**.

## Current Repository State (Phase 2 Complete)

| Area                            | Status             | Notes                                                                                         |
|---------------------------------|--------------------|-----------------------------------------------------------------------------------------------|
| Repository skeleton             | ✅ **Working**      | Monorepo layout established for modular development.                                          |
| JSON schemas                    | ✅ **Working**      | Validation tests for device, event, health, observation contracts.                            |
| Node simulator                  | ✅ **Working**      | Deterministic simulator generates schema-compatible payloads.                                 |
| Gateway service                 | ✅ **Working**      | FastAPI + SQLite; ingest, read tools, approval-gated command queue, dashboard.                |
| Gateway MCP stdio bridge        | ✅ **Working**      | JSON-RPC stdio bridge; initialize, tools/list, tools/call, ping.                             |
| Approval-gated tools            | ✅ **Working**      | capture_now and apply_config_patch queue pending commands; policy enforced.                   |
| Gateway command poll endpoint   | ✅ **Working**      | GET /api/v1/commands/{device_id}/pending; marks delivered; POST ack with result merge.        |
| Gateway capabilities endpoint   | ✅ **Working**      | GET /api/v1/devices/{device_id}/capabilities; flags for each capability group.                |
| ESP-Claw capability groups      | ✅ **Working**      | Header-only firmware macros; CLAWCAM_ESP32_S3_EYE_CAPABILITIES in device registration JSON. |
| Firmware NVS config             | ✅ **Working**      | clawcam_config: load/save/reset/patch; JSON patch via apply_config_patch command.            |
| Firmware command client         | ✅ **Working**      | clawcam_command_client: polls gateway, dispatches capture_now/apply_config_patch, acks.       |
| Firmware capture loop           | ✅ **Working**      | Deterministic PIR → capture → command poll → deep sleep; config-driven sleep intervals.      |
| Firmware deep sleep             | ✅ **Working**      | EXT0 PIR wake + timer fallback; battery-aware extended sleep from NVS config.                |
| Brain adapter                   | ✅ **Working**      | ClawCamAdapter: subprocess stdio, tool discovery, approval policy, OBC registration.         |
| End-to-end Phase 1 tests        | ✅ **Working**      | Five-layer integration test: simulator → DB → Python tools → MCP → brain adapter.            |
| Phase 2 gateway tests           | ✅ **Working**      | Command poll, ack, capabilities, full lifecycle (queue → poll → ack → empty).                |
| Cloud backend                   | 🔲 **Planned**      | Deferred until local system achieves MVP with real hardware.                                  |
| MQTT bridge                     | 🔲 **Planned**      | Phase 3; gateway ↔ node real-time channel.                                                    |
| AI model inference              | 🔲 **Planned**      | Phase 3; SpeciesNet / MegaDetector pipeline in gateway.                                       |

Ground Rules:
- No feature will be described as "Working" until verified with tests and reproducible steps.

## Phase 2 Complete — Command Transport & Persistent Config

Phase 2 closes the command loop between the brain and physical nodes:

1. **Gateway command queue** is now polled by nodes via `GET /api/v1/commands/{device_id}/pending`.
   Commands are marked "delivered" on poll; nodes ack via `POST /api/v1/commands/{command_id}/ack`.
2. **Capability groups** (`cap_clawcam_camera_trap`, etc.) are declared in firmware using a
   header-only macro and checked by `capture_now` before queuing a command.
3. **NVS-backed config** (`clawcam_config`) stores deployment metadata and sleep intervals;
   updated live via `apply_config_patch` gateway commands without reflashing.
4. **Firmware command client** (`clawcam_command_client`) polls the gateway on each wake cycle,
   dispatches `capture_now` and `apply_config_patch`, and acks results — all gated behind
   `CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED` so the node compiles cleanly without a gateway.
5. **Brain adapter** auto-approves `list_capabilities` alongside the existing read-only tools.

## Next Milestone (Phase 3): Real-Time Transport & AI Inference

- MQTT bridge: real-time gateway ↔ node and gateway ↔ brain channels
- SpeciesNet / MegaDetector inference pipeline triggered on image ingest
- OTA firmware update command via gateway queue
- Cloud storage backend for off-site media archival

---