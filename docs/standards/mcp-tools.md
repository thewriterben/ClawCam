# ClawCam MCP Tool Catalog

> **Generated from code** (`clawcam_gateway.mcp_server.stdio_server.tool_catalog()`) on 2026-07-04.
> Do not hand-edit tool rows; regenerate when tools change. The single source of
> truth is `TOOL_DEFINITIONS` + `APPROVAL_REQUIRED_TOOLS` in `stdio_server.py` —
> the MCP stdio server, `GET /api/v1/tools`, and the Oh-Ben-Claw adapter all derive from it.

**46 tools total: 35 auto-approved reads, 11 approval-gated writes.**

The stdio server speaks two protocol lifecycles: `legacy-2024` and `2026-07-28`.
No MCP resources are currently implemented (tools only).

## Approval-gated tools (write scope required)

These mutate device or gateway state. Via the REST bridge (`POST /api/v1/tools/{name}`)
they require an API key with `write` scope when auth is enabled; via the Oh-Ben-Claw
adapter they always prompt for approval.

| Tool | Description |
|---|---|
| `apply_config_patch` | Apply an approved configuration patch to a node. Approval-gated; patch is queued for node pickup. |
| `apply_profile_alert_rules` | Seed a device with the recommended alert rules for its profile (one rule per template, scoped to the device). Approval-gated — creates gateway state. |
| `capture_now` | Request a manual capture from a reachable ClawCam node. Approval-gated; requires cap_clawcam_camera_trap. |
| `create_alert_rule` | Create a persistent alert rule that fires a webhook when the AI detects matching species, labels, or confidence. Approval-gated — permanently modifies gateway state. |
| `create_detection_zone` | Create a polygon detection zone on a device. Approval-gated. Polygon is a list of [x, y] points in image-normalised coordinates (0-1). Useful for 'ignore the street, alert on the driveway' or 'black out the neighbor's window'. |
| `create_schedule` | Create a recurring or one-shot schedule that fires an action at the specified time(s). Approval-gated. Use cron_expr for recurring (UTC) or starts_at/ends_at for a time window. |
| `queue_firmware_update` | Queue an OTA firmware update for a ClawCam node. Approval-gated; requires cap_clawcam_firmware_ota. Node downloads and verifies SHA256 before flashing. |
| `set_deployment_state` | Change an entire deployment's runtime state. All devices that haven't set their own state inherit it. Approval-gated. |
| `set_device_detector_chain` | Override the detector chain for a single device. Pass null/empty chain to clear the override and revert to profile defaults. Approval-gated. |
| `set_device_state` | Change a device's runtime state (normal, armed, disarmed, away, vacation, feeding, maintenance). Approval-gated — affects which alert rules fire. Every transition is audit-logged. |
| `set_review_state` | Set the human-review state on an AI classification by result_id. Approval-gated and non-destructive: the original machine detection is preserved; only review metadata (state, reviewer, note, timestamp) changes. |

## Auto-approved read tools

| Tool | Description |
|---|---|
| `export_detections_csv` | Export recent inference detection results as a CSV string. Useful for downloading structured detection data for analysis or reporting. |
| `generate_daily_summary` | Generate a structured summary from recent gateway events. |
| `get_activity_report` | Per-subject hour-of-day activity and diel pattern (nocturnal/diurnal/crepuscular/cathemeral) over recent detections. Answers 'when are deer active here?'. |
| `get_anomaly_report` | Flag unusually busy or quiet days in the detection series: each day's count is z-scored against the site baseline; days beyond a threshold are surfaced as spikes (surges) or drops (a knocked camera / obstruction). Complements the trend report (direction vs outlier days). Read-only. |
| `get_audio_for_event` | Return all uploaded audio files plus their classifications for a single event. |
| `get_calibration_report` | Confidence calibration from human review: uses reviewed detections (verified/corrected = real, rejected = false positive) to check whether higher confidence means higher correctness, and recommends an auto-accept threshold meeting a target precision. Answers 'can I trust confidence >= X, and what should X be?'. Read-only. |
| `get_cloud_sync_status` | Return cloud upload status for gateway media files. Shows how many images are pending, uploaded, or failed for off-site archival. |
| `get_comparison_report` | Compare the last window_days of detections against the window before it: totals + percent change, newly-present vs vanished subjects, per-subject count deltas, richness delta, and whether the dominant subject changed. Answers 'how does this week compare to last?'. |
| `get_device_detector_chain` | Return the resolved detector chain for a device: per-device override (if any) or the profile defaults. This is what runs on every image uploaded from that device. |
| `get_device_state` | Return the profile, current state, and effective state of a device. Effective state falls back to the deployment state if the device's own state is unset. |
| `get_diversity_report` | Species diversity metrics over recent detections: richness, Shannon index, evenness, and dominance. Answers 'is this a diverse site or a one-species show?'. |
| `get_encounter_report` | Collapse lingering camera-trap captures into independent encounters: consecutive same-subject detections closer than gap_minutes count as one visit. Returns encounter vs raw counts per subject (with a compression ratio) plus the encounter list. Use for the honest 'how many visits?' number instead of raw frame counts. |
| `get_event_inference_chain` | Return every inference_results row for a single event in execution order. Useful when multiple detectors run on the same image (e.g. MegaDetector + bird classifier + face recognizer). |
| `get_fused_detections` | Fuse an event's detector-chain results into one consolidated detection set: overlapping boxes from different detectors merge, with localisation from the strongest box, the most specific label, and species carried over from a classifier. Read-only. Use to answer 'what is actually in this capture?' when a chain of detectors ran. |
| `get_inference_results` | Return species detection results for a specific captured event. |
| `get_node_health` | Return the latest health payload for a ClawCam node. |
| `get_recent_detections` | Return recent ClawCam event/detection records from the gateway database. |
| `get_review_queue` | Rank unreviewed detections by how much they need a human look: borderline-confidence hits, confident boxes with no species ID, and configured rare species lead; confident identified detections sink. Read-only. Use to decide what to review first instead of going chronologically. |
| `get_site_report` | One combined site summary: activity (hour-of-day + diel), trends (rising/falling), and the alert digest, with a headline. Answers 'what's happening at this site?'. |
| `get_trend_report` | Day-over-day detection trends per subject (rising/falling/steady) with a daily time series. Answers 'are deer sightings increasing here?'. |
| `list_alert_rules` | Return all configured alert rules. Rules fire webhook notifications when AI detections match specified criteria (label, species, confidence threshold). |
| `list_audio_classifications` | List recent audio classifier hits (BirdNET bird calls, glass-break, scream, dog-bark, etc.). Each row carries label, species, confidence, and the time offset within the audio file. |
| `list_capabilities` | Return the ESP-Claw capability groups declared by a ClawCam node. |
| `list_detection_zones` | List polygon detection zones for a device or across the gateway. Zones have a per-zone action: alert (default), record (no webhook), ignore (drop detection), or privacy_mask (black out the region in stored images). |
| `list_detectors` | Return the registry of detectors known to the gateway with their availability status. Useful for discovering what models are installed before configuring a detector chain. |
| `list_firmware_builds` | List all firmware binaries uploaded to the gateway, with build_id, version, SHA256, and download URL. |
| `list_observations_for_review` | List AI classifications in a given human-review state (triage queue): unreviewed, verified, corrected, rejected, needs_review. Read-only. |
| `list_pending_commands` | Return commands queued for field nodes (captures, config patches). Read-only. |
| `list_profile_alert_templates` | Preview the recommended alert rules for a device profile (e.g. livestock predator alerts, security person/vehicle alerts) without creating anything. Read-only. |
| `list_profiles` | List all available ClawCam device profiles (wildlife trail cam, home security, bird feeder, livestock, apiary, garden, driveway, etc.) with their per-profile defaults: detectors to run, capture cadence, audio on/off, alert priorities. |
| `list_recent_alerts` | Return recent fired alert events showing which rules matched, what was detected, and whether webhook delivery succeeded. |
| `list_schedule_runs` | Audit log of past schedule firings, with status (success/failed) and per-run detail. |
| `list_schedules` | List configured schedules. Schedules fire actions (set_state, enable/disable rule, webhook) on cron expressions or one-shot time windows. |
| `list_species_detections` | List recent inference results with optional filtering by label, species, or confidence. Useful for 'what animals were detected?' queries. |
| `list_state_transitions` | Audit log of state transitions for devices and deployments. Useful for diagnosing 'why didn't my alert fire?' style questions. |
