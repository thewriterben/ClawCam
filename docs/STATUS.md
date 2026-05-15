# ClawCam Status

This document is the source of truth for current implementation maturity. ClawCam tracks progress for **working code**, **scaffolds**, **frameworks**, and **planned features**.

## Current Repository State (Phase 5 Complete)

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

## Next Milestone: Hardware Integration

- Deploy on physical ESP32-S3-EYE; end-to-end field test with real PIR triggers and JPEG captures
- Validate MQTT connectivity and OTA firmware update on device

---