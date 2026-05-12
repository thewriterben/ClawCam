# ClawCam Architecture

ClawCam is designed as a layered, field-resilient wildlife monitoring system. It merges lessons from camera-trap firmware, edge gateways, and claw-based agent frameworks into one coherent product architecture.

## System Overview

```text
Field Trigger
  ↓
ClawCam Node
  ↓
ClawCam Gateway
  ↓
ClawCam Brain
  ↓
Optional Cloud / Research Export
```

The node performs deterministic capture and low-power operation. The gateway performs durable local data management and heavier computation. The brain performs agentic reasoning, reporting, and orchestration. Cloud services remain optional until the local system is dependable.

## Layer Responsibilities

| Layer | Runtime | Responsibilities | Non-Responsibilities |
|---|---|---|---|
| **Node** | ESP32-S3, ESP32-P4, or selected ESP32-CAM boards | PIR/timer/manual capture, media storage, metadata, battery state, optional lightweight inference, ESP-Claw-style capabilities. | Full global species classification, long-running LLM loops, cloud-only dependence. |
| **Gateway** | Raspberry Pi, Jetson, mini PC, or local server | Ingest, validation, media cache, SQLite/Postgres storage, AI inference, local dashboard/API, MCP server, MQTT bridge, offline sync queue. | Replacing deterministic node safety behavior. |
| **Brain** | Oh-Ben-Claw-compatible host or server | Natural-language operations, tool calling, multi-agent workflows, reports, review triage, maintenance planning, approval policy. | Mandatory operation for basic capture and storage. |
| **Cloud** | Optional hosted services | Multi-site collaboration, long-term storage, project dashboards, standards-aware export. | Required dependency for field deployment MVP. |

## Data Flow

A typical wildlife event begins with a PIR sensor, timer, remote command, or local rule. The node captures media, writes metadata, and publishes an event summary. The gateway validates the event, stores it, optionally runs heavier AI classification, and exposes the resulting records to dashboards and agents. The brain can then query detections, ask for images, summarize activity, diagnose node health, or propose configuration changes.

## Agentic Boundaries

Agentic behavior must remain layered above reliable embedded behavior. A node should always be able to capture, save, sleep, and recover without internet connectivity or model availability. Agents may configure, explain, summarize, review, and recommend, but destructive or privacy-sensitive operations require approval.

## Protocols

| Protocol | Role |
|---|---|
| **HTTP** | Simple node-to-gateway ingestion and dashboard/API access. |
| **MQTT** | Lightweight telemetry, gateway events, and Oh-Ben-Claw spine compatibility. |
| **MCP** | Standard AI-client access to ClawCam tools and resources. |
| **LoRa** | Low-bandwidth remote field event summaries and telemetry. |
| **File import** | Manual SD-card or offline batch ingestion for remote deployments. |

## On-Device Capability Groups

The ESP-Claw-compatible node target should eventually expose wildlife-specific capability groups.

| Capability Group | Purpose |
|---|---|
| `cap_clawcam_camera_trap` | Capture media, list recent captures, read camera status, and update safe capture settings. |
| `cap_clawcam_power` | Read battery/solar state and change power profile within approved limits. |
| `cap_clawcam_storage` | Query free space, list media, and report storage health. |
| `cap_clawcam_sensors` | Read environment, GPS, light, and optional external sensors. |
| `cap_clawcam_events` | Publish wildlife events, health events, and maintenance events to gateway/router. |

## Gateway Tool Catalog

The first gateway tools should be small, auditable, and useful to the brain.

| Tool | Purpose |
|---|---|
| `get_recent_detections` | Return recent detection/event summaries. |
| `get_detection` | Return one detection with metadata and media references. |
| `get_node_health` | Return battery, storage, last seen, and error state. |
| `capture_now` | Request a manual capture from a reachable node. |
| `generate_daily_summary` | Create a structured summary from stored events. |
| `list_review_tasks` | Return AI classifications needing human review. |

## Safety Model

ClawCam uses a conservative policy model. Reading data and generating summaries can be automatic. Capture requests, configuration changes, deletions, publication, cloud sync of sensitive locations, and firmware updates should require explicit approval until project policy says otherwise.
