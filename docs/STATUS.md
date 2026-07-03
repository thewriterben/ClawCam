# ClawCam Status

This document is the source of truth for current implementation maturity. ClawCam tracks progress for **working code**, **scaffolds**, **frameworks**, and **planned features**.

## Current Repository State (Phase 13 Complete)

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
| Firmware command client         | ✅ **Working**      | clawcam_command_client: polls gateway, dispatches capture_now/apply_config_patch/OTA, acks.  |
| Firmware capture loop           | ✅ **Working**      | Deterministic PIR → capture → command poll → deep sleep; config-driven sleep intervals.      |
| Firmware deep sleep             | ✅ **Working**      | EXT0 PIR wake + timer fallback; battery-aware extended sleep from NVS config.                |
| Brain adapter                   | ✅ **Working**      | ClawCamAdapter: subprocess stdio, tool discovery, approval policy, OBC registration.         |
| End-to-end Phase 1 tests        | ✅ **Working**      | Five-layer integration test: simulator → DB → Python tools → MCP → brain adapter.            |
| Phase 2 gateway tests           | ✅ **Working**      | Command poll, ack, capabilities, full lifecycle (queue → poll → ack → empty).                |
| AI inference pipeline           | ✅ **Working**      | BaseDetector/MockDetector/MegaDetectorV5; media upload → inference → results in SQLite.      |
| Inference MCP tools             | ✅ **Working**      | get_inference_results, list_species_detections; auto-approved by brain adapter.              |
| Phase 3A inference tests        | ✅ **Working**      | Detector abstraction, pipeline, DB methods, REST endpoints, tool functions — all covered.    |
| MQTT bridge (gateway)           | ✅ **Working**      | paho-mqtt bridge; subscribes to events/health/ack; publishes commands on queue.              |
| MQTT firmware component         | ✅ **Working**      | clawcam_mqtt: publishes events, receives commands via MQTT; falls back to HTTP.              |
| MQTT command push               | ✅ **Working**      | capture_now/apply_config_patch push immediately to node MQTT topic on queue.                 |
| Phase 3B MQTT tests             | ✅ **Working**      | Topic naming, event/health/ack routing, command publish, ToolContext integration.            |
| OTA firmware update             | ✅ **Working**      | Phase 3C; gateway serves .bin; queue_firmware_update tool; clawcam_ota component.           |
| Phase 3C OTA tests              | ✅ **Working**      | Firmware upload/list/download REST, DB CRUD, tool functions, dispatch, adapter policy.       |
| Cloud storage backend           | ✅ **Working**      | BaseCloudStore/S3Store/GCSStore/NoopStore; cloud_uploads tracking; auto-upload on media post. |
| Cloud MCP tool                  | ✅ **Working**      | get_cloud_sync_status; auto-approved; reports pending/uploaded/failed counts per event.       |
| Phase 4 cloud tests             | ✅ **Working**      | Store abstraction, worker, DB CRUD, REST endpoint, tool, config env-vars, adapter policy.    |
| CSV data export                 | ✅ **Working**      | events_to_csv/detections_to_csv helpers; GET /export/events.csv and /export/detections.csv.  |
| Cloud upload retry              | ✅ **Working**      | POST /api/v1/cloud/retry re-queues all failed uploads as background tasks.                   |
| Dashboard enrichment            | ✅ **Working**      | Inference summary, top species, cloud sync panels, export download links, 30 s auto-refresh. |
| export_detections_csv MCP tool  | ✅ **Working**      | Returns CSV text inline; auto-approved; filters by label, species, confidence.               |
| Phase 5 export tests            | ✅ **Working**      | CSV helpers, REST endpoints, cloud retry, dashboard payload/HTML, MCP tool, adapter policy.  |
| Alert rules engine              | ✅ **Working**      | AlertRule matching (label/confidence/species/device); AlertEvaluator as BackgroundTask.       |
| Webhook delivery                | ✅ **Working**      | deliver_webhook: stdlib urllib, 5 s timeout, never raises, records status in alert_events.    |
| Alert REST endpoints            | ✅ **Working**      | POST/GET/PATCH/DELETE /api/v1/alert-rules; GET /api/v1/alerts with filters.                  |
| Alert MCP tools                 | ✅ **Working**      | list_alert_rules, list_recent_alerts (auto-approved); create_alert_rule (approval-gated).    |
| Phase 6 alert tests             | ✅ **Working**      | Rule matching, webhook, evaluator, DB CRUD, REST, tools, dispatch, stdio, adapter, config.   |
| API key auth + scopes           | ✅ **Working**      | Hashed tokens; ordered scopes (admin ≥ write ≥ read); AuthContext injected per request.       |
| Deployments (multi-tenant)      | ✅ **Working**      | deployments CRUD; api_keys bound to deployment_id; queries scoped per tenant.                 |
| Phase 7 auth tests              | ✅ **Working**      | Token hashing, scope satisfaction, key CRUD/revoke, deployment scoping, disabled-auth mode.   |
| Device profiles                 | ✅ **Working**      | 10 profiles (wildlife, security, bird_feeder, livestock, apiary…) with behavioral defaults.   |
| Runtime state machine           | ✅ **Working**      | Device/deployment states (armed, away, feeding…); state_transitions audit table.              |
| Phase 8 profile/state tests     | ✅ **Working**      | Profile catalog, defaults, state validation, transitions, REST, tools, adapter policy.        |
| Schedule engine                 | ✅ **Working**      | 5-field cron (UTC) or one-shot; starts_at/ends_at gates; 30 s tick thread; run audit log.     |
| Schedule actions                | ✅ **Working**      | set_state, set_deployment_state, enable_rule, disable_rule, webhook; handlers never raise.    |
| Phase 9 scheduler tests         | ✅ **Working**      | Cron parsing, tick idempotence, action dispatch, REST CRUD, manual run, tools, adapter.       |
| Polygon detection zones         | ✅ **Working**      | Normalised [0,1] polygons; actions alert/record/ignore/privacy_mask; zone-aware alerts.       |
| Privacy masks                   | ✅ **Working**      | privacy_mask zones suppress detections before alert evaluation and tool output.               |
| Phase 10 zone tests             | ✅ **Working**      | Polygon validation, point-in-polygon, mask filtering, REST CRUD, tools, adapter policy.       |
| Audio capture pipeline          | ✅ **Working**      | POST /api/v1/audio/{event_id}; classification as BackgroundTask; results in SQLite.           |
| Audio classifier abstraction    | ✅ **Working**      | BaseAudioClassifier; BirdNET (species) + Mock (deterministic); YAMNet-style labels.           |
| Phase 11 audio tests            | ✅ **Working**      | Classifier abstraction, pipeline, DB methods, REST endpoints, tools, adapter policy.          |
| Detector registry               | ✅ **Working**      | Name → factory mapping; lazy model loading; unavailable detectors skipped silently.           |
| Multi-detector orchestration    | ✅ **Working**      | Per-profile/per-device detector chains; one event → multiple model results.                   |
| Phase 12 orchestrator tests     | ✅ **Working**      | Registry resolve/skip, chain config, orchestrator runs, REST, tools, adapter policy.          |

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

## Phase 3B Complete — MQTT Real-Time Transport

Phase 3B adds a real-time command channel between the gateway and nodes:

1. **Gateway MQTT bridge** (`mqtt_bridge/bridge.py`) connects to any MQTT 3.1.1 broker
   (Mosquitto, EMQX). Subscribes to `clawcam/+/events`, `clawcam/+/health`, `clawcam/+/ack`;
   writes to the same SQLite DB as the HTTP ingest path. Enabled via `CLAWCAM_MQTT_ENABLED=true`.
2. **Immediate command push**: when `capture_now` or `apply_config_patch` queues a command,
   it is also published to `clawcam/{device_id}/commands` (QoS 1) so connected nodes receive
   it without waiting for their next polling wake cycle.
3. **Firmware `clawcam_mqtt`** component publishes events via MQTT on each wake and waits
   3 seconds for incoming commands. Falls back to HTTP REST if the broker is unreachable.
   Compile-gated behind `CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED` — stub mode logs topics.
4. **FastAPI lifespan** starts/stops the bridge thread automatically; disabled by default
   so the gateway runs without a broker in offline/dev mode.

## Phase 3C Complete — OTA Firmware Update

Phase 3C closes the firmware update loop, enabling the brain to push new firmware to nodes without physical access:

1. **Firmware upload** (`POST /api/v1/firmware`): accepts `.bin` files, computes SHA256, assigns a `build_id`,
   stores in `firmware_builds` SQLite table. Serves binaries at stable download URLs.
2. **`queue_firmware_update` MCP tool** (approval-gated): validates device exists and declares
   `cap_clawcam_firmware_ota`, validates `build_id`, queues a `firmware_update` command with
   `firmware_url`, `sha256`, `version`, and `size_bytes`. Publishes via MQTT if connected.
3. **`list_firmware_builds` MCP tool** (auto-approved): returns all uploaded builds with
   build_id, version, SHA256, and download URL for brain discovery.
4. **`cap_clawcam_firmware_ota`** capability string added to `clawcam_capabilities.h` and
   included in `CLAWCAM_ESP32_S3_EYE_CAPABILITIES` macro — nodes declare OTA readiness in
   device registration JSON.
5. **`clawcam_ota` firmware component**: downloads binary via `esp_http_client` streaming,
   verifies SHA256 via mbedTLS, writes to OTA partition via `esp_ota_ops`, sets boot partition,
   and reboots. Stub mode logs without flashing (same gate as gateway client).
6. **Command client OTA dispatch**: `clawcam_command_client` now handles `firmware_update`
   command type; calls `ota_cb` from the config struct; acks "executed" on success, "failed"
   with error string on failure.
7. **Brain adapter policy**: `list_firmware_builds` is auto-approved; `queue_firmware_update`
   is in `always_ask` — the brain must obtain explicit user confirmation before queuing.

## Phase 4 Complete — Cloud Storage Backend

Phase 4 adds off-site media archival without changing the offline-first guarantee:

1. **`BaseCloudStore` abstraction** with three implementations:
   - `NoopStore`: always available, logs upload intent, returns `noop://` URIs — zero config needed.
   - `S3Store`: uses lazy-imported `boto3`; supports AWS S3 and any S3-compatible endpoint
     (MinIO, LocalStack) via `CLAWCAM_CLOUD_ENDPOINT_URL`.
   - `GCSStore`: uses lazy-imported `google-cloud-storage`; application-default credentials.
2. **`CloudUploadWorker`**: called from a FastAPI `BackgroundTask` after each media upload.
   Inserts a `cloud_uploads` DB row, attempts the upload, and updates status to "uploaded"
   or "failed". Never raises — the media ingest path is unaffected by cloud failures.
3. **`cloud_uploads` SQLite table**: tracks upload_id, event_id, media_path, remote_uri,
   provider, status, error, queued_at, uploaded_at. Indexed by event and status.
4. **`get_cloud_sync_status` MCP tool** (auto-approved): returns upload summary counts
   (pending/uploaded/failed) and a paginated record list with optional filters.
5. **Config**: `CLAWCAM_CLOUD_ENABLED`, `CLAWCAM_CLOUD_PROVIDER`, `CLAWCAM_CLOUD_BUCKET`,
   `CLAWCAM_CLOUD_PREFIX`, `CLAWCAM_CLOUD_REGION`, `CLAWCAM_CLOUD_ENDPOINT_URL`.
   Cloud is disabled by default — existing deployments are unaffected.

## Phase 6 Complete — Alert Rules & Webhook Notifications

Phase 6 adds a persistent, configurable alerting system so operators are notified in real-time when the AI detects specific animals, people, or other events:

1. **AlertRule data model** (`alerts/rules.py`): each rule specifies a label filter, minimum
   confidence, optional species substring, optional device filter, and a webhook URL. Rules are
   stored in the `alert_rules` SQLite table and survive gateway restarts.
2. **AlertEvaluator** (`alerts/evaluator.py`): registered as a FastAPI `BackgroundTask`
   immediately after inference completes. Loads all enabled rules, evaluates each against the
   fresh inference result, fires matching webhooks, and persists `alert_events` rows.
   Never raises — failures are logged and recorded, never block the ingest path.
3. **Webhook delivery** (`alerts/webhook.py`): pure stdlib `urllib.request` POST with
   `application/json` body, 5-second timeout, structured return tuple
   `(success, http_status, error)`. Zero external dependencies.
4. **`alert_rules` and `alert_events` SQLite tables** with indexed queries for enabled rules,
   fired events by rule, and delivery status.
5. **REST endpoints**: `POST/GET/PATCH/DELETE /api/v1/alert-rules` (full CRUD),
   `GET /api/v1/alerts` (fired events, filterable by rule or delivery status).
6. **MCP tools**:
   - `list_alert_rules` (auto-approved): returns all configured rules.
   - `list_recent_alerts` (auto-approved): returns fired events with delivery status.
   - `create_alert_rule` (approval-gated): persists a new rule. Brain must confirm before calling.
7. **`CLAWCAM_ALERT_WEBHOOK_URL`** env var: global default webhook used when a rule has no
   individual URL set. Empty/unset = no delivery (rule still fires and is recorded).

## Alert Polish — Severity & De-duplication (mirrors Oh-Ben-Claw notifications)

Brings OBC's escalation-notification polish to ClawCam's alert engine (Phase 6). Both
knobs are off/neutral by default, so existing deployments are unaffected.

1. **Rule severity** (`alerts/rules.py`): each `AlertRule` declares a severity —
   `info` / `warning` / `critical` (default `warning`). Persisted on `alert_rules`
   (migration-added column), settable via `POST /api/v1/alert-rules` and `PATCH`.
   `severity_rank()` orders the levels.
2. **Minimum-severity delivery gate** (`CLAWCAM_ALERT_MIN_SEVERITY`, default `info`):
   a rule below the gate is still **recorded** as an `alert_event` (delivery_status
   `skipped_severity`) but its webhook is not sent — "record everything, push only the
   loud stuff". The severity rides in the webhook payload for downstream routing.
3. **De-duplication** (`CLAWCAM_ALERT_DEDUP_WINDOW_S`, default `0` = off): a repeat of
   the same `(rule, device, label, species)` within the window is collapsed onto the
   last delivered alert (its `suppressed_count` is bumped) — no new row, no webhook.
   Stops a camera trap from firing a hundred webhooks at one lingering deer.
4. **Tests**: `tests/gateway/test_alert_severity_dedup.py` (6/6) — severity ordering +
   persistence, the min-severity record-but-skip gate, at/above-threshold delivery, the
   dedup rollup, and dedup-off-by-default.
5. **Periodic digest** (`alerts/digest.py`): `build_alert_digest()` rolls `alert_events`
   up by rule and by species over a trailing window (totals, delivered/skipped counts,
   and the de-duplicated `suppressed_total`). Delivered on a schedule via the new
   scheduler **`alert_digest`** action (`{url, window_s}`, reuses the webhook deliverer),
   or pulled from `GET /api/v1/alerts/digest?window_s=…`. Tests:
   `tests/gateway/test_alert_digest.py` — the pure roll-up, the `since` window query, and
   the scheduler action (via an injected deliverer). Completes the OBC mirror.

## Detection Analytics — Species Activity Report

A pure, storage-agnostic roll-up of *when* each subject is active — the question a
wildlife operator actually asks ("are the coyotes nocturnal at this site?").

1. **`analytics/activity.py`** — `build_activity_report(detections, tz_offset_hours=0)`:
   per-subject hour-of-day histogram, total count, first/last seen, peak hour, and a
   **diel-pattern** classification (nocturnal / diurnal / crepuscular / cathemeral) from
   the hour bands. No DB or framework imports, so it unit-tests in isolation and is
   reusable from REST, MCP tools, or the brain adapter.
2. **REST**: `GET /api/v1/analytics/activity` (`limit`, `species`, `min_confidence`,
   `tz_offset_hours`) fetches recent `inference_results` and returns the report.
3. **Tests**: `tests/gateway/test_activity_report.py` (8/8, import-isolated) — counts /
   peak / ranking, each diel pattern, the timezone-offset shift, and the `top_label`
   fallback + first/last-seen.
4. **MCP tool** `get_activity_report` (auto-approved) — wired through the whole
   tool-catalog SSOT: the tool fn (`tools/clawcam_tools.py`), `TOOL_DEFINITIONS` +
   dispatch (`mcp_server/`), and the brain adapter's `auto_approve` set — so the brain
   (Oh-Ben-Claw) can ask "when are deer active here?" directly over MCP, no approval.

## Phase 5 Complete — Data Export, Cloud Retry, Dashboard Enrichment

Phase 5 adds structured data export, cloud resilience, and a richer operator dashboard:

1. **CSV export helpers** (`ingest/export.py`): `events_to_csv` and `detections_to_csv` use
   `csv.DictWriter` on `io.StringIO` — no mandatory dependencies, returns plain `str` so callers
   can stream, write to disk, or embed in MCP responses.
2. **REST export endpoints**:
   - `GET /api/v1/export/events.csv`: streams all recent events as CSV with
     `Content-Disposition: attachment` and a timestamped filename. Accepts `limit` and `device_id`.
   - `GET /api/v1/export/detections.csv`: streams inference results with optional `label`,
     `min_confidence`, and `species` filters.
3. **Cloud upload retry** (`POST /api/v1/cloud/retry`): queries all `failed` cloud_uploads rows
   and re-queues each as a FastAPI `BackgroundTask`. Never blocks — returns `retried` count
   immediately.
4. **Dashboard enrichment**: `/dashboard` now includes:
   - AI Inference panel: detection label cards + per-event results table.
   - Top Species panel: top-5 species by detection count.
   - Cloud Sync panel: pending/uploaded/failed counts with cloud enabled/disabled badge.
   - Export download links in the header (events.csv, detections.csv).
   - 30-second `<meta http-equiv="refresh">` auto-refresh so operators see live state.
5. **`export_detections_csv` MCP tool** (auto-approved): returns the CSV as a plain string field
   so the brain can save it or display it inline. Accepts the same filters as the REST endpoint.
   Brain adapter policy unchanged — read-only tools need no approval.

## Phase 7 Complete — Deployments, API Key Auth & Multi-Tenant Foundation

Phase 7 lets one gateway serve multiple sites or customers safely:

1. **`deployments` table + CRUD** (`/api/v1/deployments`): a deployment is a tenant boundary.
2. **API key auth** (`auth/tokens.py`): keys are generated with `secrets`, stored as SHA256
   hashes, and bound to a `deployment_id`. Ordered scopes: `admin` ≥ `write` ≥ `read`.
3. **`AuthContext` dependency** (`api/auth_dependency.py`): resolves the inbound key, injects
   `deployment_id` and `scope` into handlers; mutating endpoints call `require("write")`.
4. **Key management endpoints**: `GET/POST /api/v1/api-keys`, revoke, and delete.
5. **Auth disabled by default** for single-user field deployments — a synthetic admin context
   is injected so existing setups keep working unchanged.

## Phase 8 Complete — Device Profiles & Runtime State Machine

Phase 8 broadens ClawCam from a wildlife camera trap into a general camera platform:

1. **Profile catalog** (`profiles/profiles.py`): `general`, `wildlife_trail_camera`,
   `home_security_outdoor`, `home_security_indoor`, `bird_feeder`, `hummingbird_feeder`,
   `livestock_watch`, `apiary`, `garden`, `driveway`. Each sets defaults for sleep policy,
   capture cadence, detector chain, alert thresholds, and audio on/off — all overridable.
2. **Runtime states** (`profiles/states.py`): `normal`, `armed`, `disarmed`, `away`,
   `vacation`, `feeding`, `maintenance`. Deliberately loose strings, not a strict FSM;
   every transition is recorded in the `state_transitions` audit table.
3. **REST**: profile list/detail, device state get/patch, deployment state patch,
   device profile patch, state-transitions query.
4. **MCP tools**: `list_profiles`, `get_device_state`, `list_state_transitions`
   (auto-approved); `set_device_state`, `set_deployment_state` (approval-gated).
5. **Alert rules** can now require a state (e.g. only fire when `armed`).

## Phase 9 Complete — Cron Schedule Engine & Persistent Scheduled Actions

Phase 9 adds time-driven automation ("arm the driveway cam at 10pm"):

1. **`ScheduleEngine`** (`scheduler/engine.py`): synchronous, idempotent `tick(now)` driven by
   a 30-second background thread; fully unit-testable with explicit timestamps.
2. **Schedule model**: 5-field cron expression (UTC) or one-shot (`cron_expr` NULL);
   `starts_at`/`ends_at` window gates; persisted in SQLite with a `schedule_runs` audit log.
3. **Action types** (`scheduler/actions.py`): `set_state`, `set_deployment_state`,
   `enable_rule`, `disable_rule`, `webhook`. Handlers never raise — failures are recorded.
4. **REST**: schedules CRUD, manual `POST /api/v1/schedules/{id}/run`, `GET /api/v1/schedule-runs`.
5. **MCP tools**: `list_schedules`, `list_schedule_runs` (auto-approved);
   `create_schedule` (approval-gated).

## Phase 10 Complete — Polygon Detection Zones & Privacy Masks

Phase 10 adds spatial awareness to detections:

1. **Zone geometry** (`zones/geometry.py`): polygons with ≥3 vertices, coordinates normalised
   to [0,1] so zones survive re-framing and resolution changes.
2. **Zone actions**: `alert`, `record`, `ignore`, `privacy_mask`.
3. **Privacy masks** (`zones/masks.py`): detections inside a `privacy_mask` zone are suppressed
   before alert evaluation and excluded from tool output.
4. **Alert evaluator** is zone-aware: `ignore` zones drop matches; `alert` zones route them.
5. **REST**: `/api/v1/zones` full CRUD. **MCP tools**: `list_detection_zones` (auto-approved);
   `create_detection_zone` (approval-gated).

## Phase 11 Complete — Audio Capture, Classification & Storage

Phase 11 gives nodes ears, mirroring the visual inference pipeline:

1. **`BaseAudioClassifier`** (`audio/classifier.py`): returns `AudioClassification` dataclasses
   shaped like visual `Detection`s so alerts, schedules, and tools reuse one vocabulary.
2. **Implementations**: `BirdNETClassifier` (species ID, lazy-loaded) and
   `MockAudioClassifier` (deterministic seeded results for CI). Label vocabulary covers
   YAMNet-style events: `bird`, `glass_break`, `gunshot`, `scream`, etc.
3. **Audio upload** (`POST /api/v1/audio/{event_id}`): classification runs as a FastAPI
   `BackgroundTask`; results persist to SQLite with time offsets and durations.
4. **REST**: per-event classifications and `GET /api/v1/audio/recent`.
5. **MCP tools**: `list_audio_classifications`, `get_audio_for_event` (auto-approved).

## Phase 12 Complete — Multi-Detector Orchestration

Phase 12 lets one event run a chain of models instead of a single detector:

1. **`DetectorRegistry`** (`inference/registry.py`): name → factory mapping; factories are
   lazy so heavy models (face recognition, OCR) only load when a device needs them;
   unknown/unavailable detectors are skipped silently.
2. **Per-profile default chains**: e.g. a bird feeder runs MegaDetector + a species classifier;
   a security camera could run MegaDetector + face recognizer + plate OCR.
3. **Per-device overrides**: `PATCH /api/v1/devices/{device_id}/detector-chain`.
4. **Orchestrator** (`inference/orchestrator.py`): runs each chain entry against an uploaded
   image, persisting one inference result row per detector.
5. **REST**: `GET /api/v1/detectors`, device detector-chain get/patch,
   `GET /api/v1/events/{event_id}/inference/chain`.
6. **MCP tools**: `list_detectors`, `get_device_detector_chain`, `get_event_inference_chain`
   (auto-approved); `set_device_detector_chain` (approval-gated).

## Phase 13 Complete — Production Hardening (lockstep with Oh-Ben-Claw Phase 15)

All Phase 13 deliverables are code-complete and tested (see `NEXT_PHASE_PLAN.md`):

1. **MCP 2026-07-28 readiness**: dual-mode stdio bridge + gateway (`legacy-2024` / `stateless-2026`);
   cross-repo integration suite green in both modes (`tests/integration/test_phase15_cross_repo_mcp.py`)
   and now part of the CI gate. One calendar action remains: flip the default `protocol_mode` to
   `stateless-2026` on July 28, 2026.
2. **Evaluation harness**: golden flows on MockDetector + full policy-partition eval; `tests/evals` is a CI release gate.
3. **Observability**: `tool_call_audit` at the dispatch chokepoint; `GET /api/v1/metrics`; `GET /api/v1/tool-audit`.
4. **Approval-model upgrade**: call/session/forever scopes + plan-mode argument bounds, wire-compatible with Oh-Ben-Claw.
5. **CI gate widened**: `tests/integration` added to pytest testpaths; full gated suite green (678 passed).
6. **Repo hygiene**: `.gitattributes` normalizes line endings to LF; simulator emits canonical `cap_clawcam_*` capabilities.

## Next Milestone: Hardware Integration (Phase 14)

- Deploy on physical ESP32-S3-EYE; end-to-end field test with real PIR triggers and JPEG captures
- Validate MQTT connectivity and OTA firmware update on device
- See `docs/PHASE14_FIELD_TEST_PLAN.md` for the detailed runbook

---