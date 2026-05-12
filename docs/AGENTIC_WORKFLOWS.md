# ClawCam Agentic Workflows

ClawCam uses agents to make field operations easier, but agents do not replace reliable embedded behavior. The node remains deterministic for capture, storage, and sleep. Agents operate through documented gateway and node tools.

## Agent Roles

| Agent | Responsibility | Typical Outputs |
|---|---|---|
| Wildlife Analyst | Summarizes detections, activity windows, species patterns, and notable media. | Daily report, weekly report, species table, review queue. |
| Field Technician | Diagnoses battery, storage, connectivity, clock drift, sensor, and camera failures. | Maintenance checklist, site visit priority, configuration recommendation. |
| Data Steward | Prepares reviewed observations, export packages, and publication-ready metadata. | Camtrap DP export notes, missing metadata report, privacy warnings. |
| Review Assistant | Prioritizes uncertain, rare, or policy-sensitive classifications for human verification. | Review task list and suggested labels. |
| Configuration Advisor | Recommends safe capture intervals, sensitivity, power profile, and upload policy. | Proposed configuration patch requiring approval. |

## Tool Categories

| Category | Examples | Approval Requirement |
|---|---|---|
| Read-only | `get_recent_detections`, `get_node_health`, `get_gateway_health` | No approval by default. |
| Analysis | `generate_daily_summary`, `get_species_counts`, `list_review_tasks` | No approval by default. |
| Capture | `capture_now`, `request_diagnostic_image` | Approval recommended unless local operator enables automatic mode. |
| Configuration | `set_capture_interval`, `set_motion_sensitivity`, `set_power_profile` | Approval required. |
| Destructive | `delete_media`, `purge_database`, `factory_reset_node` | Approval always required. |
| Publication | `sync_cloud`, `export_public_dataset`, `publish_location` | Approval always required. |
| Firmware | `ota_update_node`, `rollback_firmware` | Approval always required. |

## First Skills

Skills are user-facing workflows built on lower-level tools.

| Skill | Directory | Purpose |
|---|---|---|
| Daily Wildlife Report | `skills/daily-wildlife-report/` | Generate a daily field summary from detections and health state. |
| Camera Health Diagnosis | `skills/camera-health-diagnosis/` | Diagnose camera, battery, storage, radio, and clock problems. |
| Field Maintenance Planner | `skills/field-maintenance-planner/` | Prioritize field visits and generate maintenance tasks. |
| Species Review Workflow | `skills/species-review-workflow/` | Triage AI labels and prepare human review batches. |

## Safety Boundary

Agents can recommend configuration changes, but approved gateway policies must enforce limits. For example, an agent may propose shortening capture intervals during peak wildlife activity, but gateway policy should reject changes that exceed battery or storage constraints.

## Human-in-the-Loop Review

Human review is required for rare species alerts, low-confidence classifications, publication exports, sensitive location sharing, destructive operations, and large cloud sync actions.
