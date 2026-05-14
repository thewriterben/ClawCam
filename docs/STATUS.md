# ClawCam Status

This document is the source of truth for current implementation maturity. ClawCam tracks progress for **working code**, **scaffolds**, **frameworks**, and **planned features**.

## Current Repository State (Phase 3A Complete)

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
| AI inference pipeline           | ✅ **Working**      | BaseDetector/MockDetector/MegaDetectorV5; media upload → inference → results in SQLite.      |
| Inference MCP tools             | ✅ **Working**      | get_inference_results, list_species_detections; auto-approved by brain adapter.              |
| Phase 3A inference tests        | ✅ **Working**      | Detector abstraction, pipeline, DB methods, REST endpoints, tool functions — all covered.    |
| Cloud backend                   | 🔲 **Planned**      | Deferred until local system achieves MVP with real hardware.                                  |
| MQTT bridge                     | 🔲 **Planned**      | Phase 3B; gateway ↔ node real-time channel.                                                   |
| OTA firmware update             | 🔲 **Planned**      | Phase 3B; update command via gateway queue + ESP-IDF OTA API.                                 |

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

## Phase 3A Complete — AI Inference Pipeline

Phase 3A adds species detection to every uploaded image, without blocking the event ingest path:

1. **Detector abstraction** (`BaseDetector`) with two implementations:
   - `MockDetector`: deterministic seeded fake results — always available, reproducible in tests.
   - `MegaDetectorV5`: wraps ultralytics YOLO; lazy-loads weights; gracefully absent in CI.
   - `get_detector()` factory picks the best available implementation automatically.
2. **Media upload endpoint** (`POST /api/v1/media/{event_id}`): nodes upload JPEGs after submitting
   event metadata. Inference runs as a FastAPI `BackgroundTask` — the response returns immediately.
3. **`inference_results` table**: stores model name, version, detections JSON, top label,
   confidence, and species per event. Indexed for fast label/species/confidence queries.
4. **New REST endpoints**: `GET /api/v1/events/{event_id}/inference` and
   `GET /api/v1/inference/recent` with label, species, and confidence filters.
5. **New MCP tools**: `get_inference_results` and `list_species_detections` — both auto-approved
   by the brain adapter, enabling queries like "what animals were detected today?"

## Next Milestone (Phase 3B): Real-Time Transport & OTA

- MQTT bridge: real-time gateway ↔ node channel (eliminates polling for urgent commands)
- OTA firmware update: gateway queues update command; node downloads via ESP-IDF OTA API
- Cloud storage backend for off-site media archival

---