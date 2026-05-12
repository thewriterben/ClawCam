# MCP Tool Direction

ClawCam should expose gateway data and safe operations through an MCP server so AI clients can interact with wildlife monitoring deployments through a standard tool/resource interface.

## Initial MCP Tools

The shared Python dispatcher for these tools starts in `gateway/clawcam_gateway/mcp_server/tool_dispatch.py`. It is not a complete MCP server yet, but it gives future MCP, HTTP, and Oh-Ben-Claw adapters a single implementation path.

| Tool | Purpose | Approval |
|---|---|---|
| `get_recent_detections` | Return recent event and observation summaries. | Not required. |
| `get_detection` | Return one detection with metadata and media references. | Not required. |
| `get_node_health` | Return node health and telemetry. | Not required. |
| `generate_daily_summary` | Summarize recent detections and health state. | Not required. |
| `capture_now` | Request a manual capture from a reachable node. | Recommended. |
| `propose_config_patch` | Generate a safe configuration change proposal. | Required before apply. |
| `apply_config_patch` | Apply an approved configuration patch. | Required. |

## Initial MCP Resources

| Resource | Purpose |
|---|---|
| `clawcam://devices` | List known nodes and gateways. |
| `clawcam://detections/recent` | Recent detections. |
| `clawcam://health` | Gateway and fleet health. |
| `clawcam://schemas` | JSON schemas used by ClawCam. |

## Safety Policy

MCP tools that mutate state, publish data, delete media, sync sensitive data, or update firmware must require approval. Read-only tools and summary generation may run automatically.
