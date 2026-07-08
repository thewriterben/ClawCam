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

## Phase 3: Real-Time Transport & AI Inference (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| AI inference pipeline    | MegaDetector runs on image ingest as a BackgroundTask; results written to inference_results table. (3A)      | ✅ Completed  |
| MQTT bridge              | Gateway publishes commands and receives events/health/acks over MQTT; immediate command push. (3B)            | ✅ Completed  |
| OTA firmware update      | Gateway serves .bin builds; queue_firmware_update tool; node downloads, verifies SHA256, flashes via OTA. (3C)| ✅ Completed  |

## Phase 4: Cloud Storage Backend (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Cloud store abstraction  | BaseCloudStore with S3, GCS, and Noop implementations; lazy imports; disabled by default.                    | ✅ Completed  |
| Upload tracking          | cloud_uploads table tracks pending/uploaded/failed; auto-upload on media post; never blocks ingest.           | ✅ Completed  |
| get_cloud_sync_status    | Auto-approved MCP tool reports upload counts and records.                                                     | ✅ Completed  |

## Phase 5: Data Export, Cloud Retry, Dashboard (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| CSV export               | GET /export/events.csv and /export/detections.csv with filters; export_detections_csv MCP tool.               | ✅ Completed  |
| Cloud upload retry       | POST /api/v1/cloud/retry re-queues failed uploads as background tasks.                                        | ✅ Completed  |
| Dashboard enrichment     | Inference summary, top species, cloud sync panels, export links, 30 s auto-refresh.                           | ✅ Completed  |

## Phase 6: Alert Rules & Webhook Notifications (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Alert rules engine       | AlertRule matching on label/confidence/species/device; AlertEvaluator as BackgroundTask.                      | ✅ Completed  |
| Webhook delivery         | stdlib urllib POST, 5 s timeout, never raises; delivery status recorded in alert_events.                      | ✅ Completed  |
| Alert REST + MCP tools   | Full CRUD endpoints; list_alert_rules/list_recent_alerts auto-approved; create_alert_rule gated.              | ✅ Completed  |

## Phase 7: Deployments, Auth & Multi-Tenancy (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Deployments              | deployments table + CRUD; tenant boundary for all data.                                                       | ✅ Completed  |
| API key auth             | Hashed tokens with ordered scopes (admin ≥ write ≥ read); AuthContext dependency; disabled by default.        | ✅ Completed  |

## Phase 8: Device Profiles & Runtime States (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Profile catalog          | 10 profiles (wildlife, security, bird_feeder, livestock, apiary, garden, driveway…) with defaults.            | ✅ Completed  |
| Runtime states           | armed/disarmed/away/vacation/feeding/maintenance; state_transitions audit table; state-aware alert rules.     | ✅ Completed  |

## Phase 9: Schedule Engine (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| ScheduleEngine           | 5-field cron (UTC) or one-shot; starts_at/ends_at gates; idempotent tick; schedule_runs audit log.            | ✅ Completed  |
| Schedule actions         | set_state, set_deployment_state, enable_rule, disable_rule, webhook.                                          | ✅ Completed  |

## Phase 10: Detection Zones & Privacy Masks (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Polygon zones            | Normalised [0,1] polygons with alert/record/ignore/privacy_mask actions; zone-aware alert evaluator.          | ✅ Completed  |
| Privacy masks            | Detections inside privacy_mask zones suppressed before alerts and tool output.                                | ✅ Completed  |

## Phase 11: Audio Pipeline (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Audio classification     | BaseAudioClassifier; BirdNET + deterministic mock; upload endpoint with BackgroundTask classification.        | ✅ Completed  |
| Audio storage + tools    | Classifications persisted with offsets/durations; list_audio_classifications, get_audio_for_event tools.      | ✅ Completed  |

## Phase 12: Multi-Detector Orchestration (100% Complete)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Detector registry        | Name → factory mapping; lazy model loading; unavailable detectors skipped gracefully.                         | ✅ Completed  |
| Detector chains          | Per-profile defaults + per-device overrides; one event runs multiple detectors; chain results queryable.      | ✅ Completed  |

## Phase 13: Production Hardening (Code-Complete — lockstep with Oh-Ben-Claw Phase 15)

Executed as one coordinated phase with Oh-Ben-Claw (see `NEXT_PHASE_PLAN.md` in the workspace root). No new product surface area. Target window: June 8 – July 31, 2026. **All deliverables are code-complete and tested; the one remaining item is a calendar action — flipping the default `protocol_mode` to `stateless-2026` on July 28, 2026.**

| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| MCP 2026-07-28 readiness | stdio bridge + gateway audited against the breaking RC (stateless core); dual-mode behind config flag; cross-repo integration suite (brain ↔ adapter ↔ bridge ↔ gateway) passes in both modes; MCP surface verified behind plain HTTP with no session affinity. | ✅ **Code-complete** — dual-mode bridge + gateway; cross-repo suite green (`tests/integration/test_phase15_cross_repo_mcp.py`, both modes), now part of the CI gate. Remaining: flip default `protocol_mode` to `stateless-2026` on Jul 28, 2026. |
| Evaluation harness       | Golden flows on MockDetector: event → inference → alert linkage + determinism contract; full policy-partition eval (all gated tools — 11 as of Phase 13+ — behaviorally ask; auto-approved never do; the eval derives the partition from the SSOT so the count never goes stale); `tests/evals` in pytest testpaths = CI release gate. | ✅ **Working** (7/7) |
| Observability            | tool_call_audit table written at the dispatch_tool chokepoint (both MCP-stdio and REST tagged by source; SHA-256 args hash; latency; never blocks dispatch); GET /api/v1/metrics (entity counts + per-tool calls/errors/avg latency); GET /api/v1/tool-audit. | ✅ **Working** (4 tests; 38/38 with regression scope) |
| Approval-model upgrade   | ToolPolicy adopts call/session/forever scope vocabulary shared with Oh-Ben-Claw; plan-mode approval with argument bounds honored by ClawCamAdapter; approval audit trail. | ✅ **Done** (WS6 scopes + plan-mode/ArgumentBound, lockstep with OBC `ApprovedPlan`) |

## Phase 14: Hardware Integration (Planned — moved from Phase 13)
| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Physical node deployment | ESP32-S3-EYE field test: real PIR triggers, JPEG captures, gateway upload.                                    | 🔲 Planned    |
| MQTT on device           | Node publishes events and receives pushed commands over a real broker.                                        | 🔲 Planned    |
| OTA on device            | Firmware update downloaded, SHA256-verified, and flashed on physical hardware.                                | 🔲 Planned    |

## Phase 15: Geospatial Foundation (Planned — Conservation Grid G0)

The ClawCam half of the ecosystem "Conservation Grid" G0 unlock (full strategy: `Oh-Ben-Claw/docs/CONSERVATION-GRID-STRATEGY.md`). Today lat/lon and environment fields exist only in the JSON-schema contract and die in `payload_json`; this promotes them to queryable, joinable, exportable data and adds a real site model. The ENU⇄geodetic coordinate conversion is defined once in Oh-Ben-Claw and consumed here — ClawCam does not fork its own geometry.

| Deliverable              | Acceptance Criteria                                                                                          | Status        |
|--------------------------|--------------------------------------------------------------------------------------------------------------|---------------|
| Geo + environment columns | Promote `latitude`/`longitude`/`altitude_m` to real columns on `events` and `temperature_c`/`humidity_percent`/`pressure_hpa` on `health_records`; populated on insert; migration backfills legacy rows from `payload_json` via `json_extract`; JSON blob preserved. | ✅ **Done** — `add_event`/`add_health` populate; idempotent backfill in `migrate()`; indexed `(latitude, longitude)`; 7 tests in `tests/gateway/test_geo_columns.py`. |
| Geo queries + export     | Indexed bounding-box event query; geo columns in the events CSV export. | ✅ **Done** — `events_in_bbox()`; `events_to_csv` gains `latitude`/`longitude`/`altitude_m`. |
| `sites` table            | First-class `sites(site_id, name, boundary_json, origin_lat, origin_lon, dem_ref, metadata_json, …)` with centroid-default origin; `deployments.site_id` link (fills the `DATA_MODEL.md` "location/covariates" gap). | ✅ **Done** — `upsert_site`/`get_site`/`list_sites`/`set_deployment_site`/`site_for_deployment`; `tests/gateway/test_sites.py`. |
| Within-polygon query     | Point-in-polygon `events_in_site()` — indexed bbox prefilter + exact ray-casting (reuses `zones.geometry.point_in_polygon`). | ✅ **Done** — square + triangle (bbox-corner exclusion) verified. |
| Geo REST/MCP surface     | Expose site queries + CRUD. Reads via MCP (`list_sites`, `get_site_events`, SSOT-wired auto-approved) **and** REST; site CRUD + deployment→site link via REST. | ✅ **Done** — `GET/POST /api/v1/sites`, `GET /api/v1/sites/{id}`, `GET /api/v1/sites/{id}/events`, `PUT /api/v1/deployments/{id}/site`; catalog +2 (→51); `tests/gateway/test_geo_surface.py`. |
| Coordinate contract      | Consume the shared Oh-Ben-Claw ENU⇄`(lat,lon)` conversion + `site` schema; round-trip test proving a detection's `(lat,lon)` ↔ site-local ENU is stable. | 🔲 Planned    |
| Quick win                | Ship the geo/environment column promotion first (data already arrives in `payload_json`) — unblocks dormant signal before the optimizer (OBC G1) exists. | ✅ **Done** (this is the geo+environment columns row above). |

> Note: the **grid coverage optimizer** and **camera-onto-mesh bridge** (Conservation Grid G1/G2) are owned by Oh-Ben-Claw (`ROADMAP.md` → Conservation Grid track). ClawCam Phase 15 is the data-layer prerequisite both depend on.

## Detailed Timeline
- **Phase 0**: Completed
- **Phases 1–2**: Completed (Q2 2026)
- **Phases 3–12**: Completed (Q2 2026)
- **Phase 13 (Production Hardening)**: June 8 – July 31, 2026 (lockstep with Oh-Ben-Claw Phase 15) — code-complete; default protocol flip scheduled for Jul 28, 2026
- **Phase 14 (Hardware Integration)**: Target Q3–Q4 2026
- **Phase 15 (Geospatial Foundation — Conservation Grid G0)**: Planned; geo/environment column promotion is the quick-win first step

---