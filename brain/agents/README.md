# ClawCam Brain Agents

ClawCam agents are specialized roles that operate through gateway tools and documented approval policies.

## Initial Agents

| Agent | Role | First Tools |
|---|---|---|
| Wildlife Analyst | Summarize detections, identify activity windows, and prepare daily reports. | `get_recent_detections`, `generate_daily_summary` |
| Field Technician | Diagnose battery, storage, camera, radio, and offline issues. | `get_node_health`, `get_recent_detections` |
| Data Steward | Prepare reviewed observations for standards-aware export and publication. | `get_recent_detections`, future export tools |
| Review Assistant | Triage low-confidence, rare, or conflicting classifications. | future review tools |

## Prompt Boundary

Agents may recommend actions, but tool policy decides whether actions can execute automatically. Destructive, publication, firmware, and configuration changes require approval.
