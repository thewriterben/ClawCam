# ClawCam Roadmap

The ClawCam roadmap is intentionally phased. Each phase must produce a working, testable increment before proceeding to the next milestone.

## Phase 0: Repository Foundation (100% Complete)
| Deliverable                | Acceptance Criteria                                                                                         | Status        |
|----------------------------|-------------------------------------------------------------------------------------------------------------|---------------|
| Monorepo skeleton          | Active source tree exists outside `legacy_archives/`.                                                       | ✅ Completed  |
| Status documentation       | `docs/STATUS.md` clearly separates working, scaffolded, framework, planned, and legacy-reference areas.     | ✅ Completed  |
| Architecture documentation | `docs/ARCHITECTURE.md` defines node, gateway, brain, and cloud responsibilities.                            | ✅ Completed  |
| Initial schemas            | Device, event, observation, and health schemas exist and are validated by tests.                            | ✅ Completed  |
| CI                         | Basic schema validation and Python test workflow exists.                                                     | ✅ Completed  |

## Phase 1: Working Vertical Slice (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Node simulator           | Schema-valid device/event/health payloads generated deterministically.                                       | ✅ Completed  |
| Gateway ingest           | Gateway validates and persists events and device registrations in SQLite.                                    | ✅ Completed  |
| Read-only tools          | get_recent_detections, get_node_health, generate_daily_summary, list_pending_commands work end-to-end.       | ✅ Completed  |
| Approval-gated commands  | capture_now and apply_config_patch queue commands; policy enforced via ClawCamAdapter.                       | ✅ Completed  |
| MCP stdio bridge         | JSON-RPC stdio server passes initialize, tools/list, tools/call, ping.                                       | ✅ Completed  |
| Brain adapter            | ClawCamAdapter launches gateway subprocess, discovers tools, enforces approval, provides OBC registration.   | ✅ Completed  |
| Firmware capture loop    | Deterministic PIR → capture → deep sleep on ESP32-S3-EYE with RTC timestamps and battery-aware sleep.       | ✅ Completed  |
| Phase 1 integration test | Five-layer test: simulator → DB → Python tools → MCP → brain adapter all pass.                              | ✅ Completed  |

## Phase 2: Command Transport & Persistent Config (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Command poll endpoint    | GET /api/v1/commands/{device_id}/pending delivers queued commands and marks them delivered.                  | ✅ Completed  |
| Ack endpoint             | POST /api/v1/commands/{command_id}/ack accepts executed/failed/skipped with result payload.                  | ✅ Completed  |
| Capabilities endpoint    | GET /api/v1/devices/{device_id}/capabilities returns list + boolean flags per capability group.              | ✅ Completed  |
| ESP-Claw capability groups | Firmware header defines standard capability strings; device registration includes them.                    | ✅ Completed  |
| NVS-backed config        | clawcam_config loads/saves/patches all node parameters; survives deep sleep cycles.                          | ✅ Completed  |
| Firmware command client  | clawcam_command_client polls gateway, dispatches capture_now/apply_config_patch, acks; gated compile.        | ✅ Completed  |
| Config-driven sleep      | Firmware uses capture_interval_s and low_battery_sleep_s from NVS config, not compile-time constants.       | ✅ Completed  |
| Phase 2 test suite       | Command poll, ack, capabilities, and full queue → poll → ack → empty lifecycle covered by tests.            | ✅ Completed  |

## Phase 3: Real-Time Transport & AI Inference (Planned)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| MQTT bridge              | Gateway publishes events and receives commands over MQTT; nodes subscribe without polling.                   | 🔲 Planned    |
| AI inference pipeline    | SpeciesNet / MegaDetector runs on image ingest; species tags written back to event record.                   | 🔲 Planned    |
| OTA firmware update      | Gateway queues firmware update command; node downloads and verifies via ESP-IDF OTA API.                     | 🔲 Planned    |
| Cloud storage backend    | Captured images archived to S3-compatible storage; gateway retains metadata pointers.                        | 🔲 Planned    |
| Multi-node dashboard     | Gateway dashboard shows live status, battery, and last-seen for all registered nodes.                        | 🔲 Planned    |

## Detailed Timeline
- **Phase 0**: Completed
- **Phase 1**: Completed (Q2 2026)
- **Phase 2**: Completed (Q2 2026)
- **Phase 3**: Target Q3 2026

---