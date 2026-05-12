# Daily Wildlife Report

## Purpose

Generate a concise daily report from ClawCam gateway data, including detections, notable media, species/activity patterns, and device health issues.

## Required Inputs

| Input | Description |
|---|---|
| `date` | Report date in `YYYY-MM-DD` format. |
| `deployment_id` | Optional deployment filter. |

## Required Tools

| Tool | Purpose |
|---|---|
| `get_recent_detections` | Retrieve recent events and detections. |
| `get_node_health` | Retrieve device health issues. |
| `generate_daily_summary` | Build the structured summary when available. |

## Output Format

The report should include an executive summary, detection table, notable events, camera health section, recommended follow-up actions, and any review tasks.
