# ClawCam Roadmap

The ClawCam roadmap is intentionally phased. Each phase must produce a working, testable increment before the next layer is treated as more than planned work.

## Phase 0: Repository Foundation

| Deliverable | Acceptance Criteria |
|---|---|
| Monorepo skeleton | Active source tree exists outside `legacy_archives/`. |
| Status documentation | `docs/STATUS.md` clearly separates working, scaffolded, framework, planned, and legacy-reference areas. |
| Architecture documentation | `docs/ARCHITECTURE.md` defines node, gateway, brain, and cloud responsibilities. |
| Initial schemas | Device, event, observation, and health schemas exist and are validated by tests. |
| CI | Basic schema validation and Python test workflow exists. |

## Phase 1: Working Vertical Slice

| Deliverable | Acceptance Criteria |
|---|---|
| Node or simulator event | A valid event payload can be produced and submitted. |
| Gateway ingest | Gateway validates and persists events. |
| Local API | Recent events and node health can be queried. |
| Brain tool | A simple agent-compatible tool can query recent detections. |
| Documentation | Setup steps reproduce the flow locally. |

## Phase 2: ESP-Claw Native Node

| Deliverable | Acceptance Criteria |
|---|---|
| ESP-IDF board target | One recommended camera board builds under ESP-IDF. |
| Wildlife capability group | Capture/status/config capabilities are registered. |
| Lua/router rules | PIR capture, low battery, storage full, and scheduled health rules are deterministic. |
| Local memory | Deployment identity and site notes persist across reboot. |

## Phase 3: AI Inference and Review

| Deliverable | Acceptance Criteria |
|---|---|
| Gateway model pipeline | Gateway stores classification outputs with model name/version/confidence. |
| Review workflow | AI labels can be verified, corrected, rejected, or deferred. |
| Model registry | Model metadata and supported hardware notes are tracked. |
| MCU filter | Optional lightweight ESP-DL or LiteRT filter exists for simple event triage. |

## Phase 4: Field Networking and Offline Reliability

| Deliverable | Acceptance Criteria |
|---|---|
| MQTT bridge | Telemetry and events publish to configured topics. |
| LoRa bridge | Low-bandwidth wildlife event summaries can be decoded and stored. |
| Offline sync queue | Cloud sync is retryable and observable. |
| Diagnostics | Gateway exposes storage, queue, radio, model, and service health. |

## Phase 5: ClawCam Brain

| Deliverable | Acceptance Criteria |
|---|---|
| Tool catalog | Gateway tools are documented and callable from the brain adapter. |
| Specialist agents | Analyst, field technician, and data steward agents have prompts and workflows. |
| Reports | Daily and weekly summaries generate from gateway data. |
| Approval policy | Sensitive operations are guarded. |

## Phase 6: Standards and Cloud

| Deliverable | Acceptance Criteria |
|---|---|
| Camtrap DP mapping | Export mapping exists for projects, deployments, media, observations, and classifications. |
| Sensitive data handling | Location privacy and publication filters exist. |
| Cloud dashboard | Optional authenticated cloud deployment is available. |
| Collaboration | Multi-user review and project workflows are implemented. |
