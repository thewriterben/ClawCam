# Oh-Ben-Claw Adapter

This adapter area defines how ClawCam gateway capabilities become callable tools for an Oh-Ben-Claw-style brain.

## Initial Integration Pattern

The gateway remains the system of record for field data. The brain calls gateway tools through MCP, HTTP, or an Oh-Ben-Claw MQTT spine bridge. Read-only tools can run automatically, while configuration changes, capture commands, publication, deletion, and firmware updates require approval.

## Initial Tool Set

| Tool | Purpose | Approval |
|---|---|---|
| `get_recent_detections` | Return recent gateway detections/events. | No |
| `get_detection` | Return one event or observation with metadata. | No |
| `get_node_health` | Return latest health for a node. | No |
| `generate_daily_summary` | Produce a structured daily report from stored events. | No |
| `capture_now` | Request manual capture from a reachable node. | Yes |
| `propose_config_patch` | Generate a safe configuration proposal. | Yes before apply |
| `apply_config_patch` | Apply approved configuration change. | Yes |

## Current Implementation

The first-pass gateway tool functions now live in `gateway/clawcam_gateway/tools/clawcam_tools.py`. They provide direct Python callables for `get_recent_detections`, `get_node_health`, `generate_daily_summary`, and structured not-yet-implemented responses for approval-gated operations such as `capture_now` and `apply_config_patch`.

## MCP-Compatible Bridge

The first MCP-compatible stdio bridge now lives in `gateway/clawcam_gateway/mcp_server/stdio_server.py`. It supports `initialize`, `tools/list`, `tools/call`, and `ping`, and it wraps the same gateway tool functions used by the Python dispatcher and HTTP tool endpoint.

Run it from the gateway directory:

```bash
PYTHONPATH=. python -m clawcam_gateway.mcp_server.stdio_server --db ../clawcam_gateway.db
```

## Next Implementation Step

Add an Oh-Ben-Claw example configuration that launches this stdio bridge and maps its read-only tools into the brain. After that, replace or complement the lightweight bridge with a full SDK-backed MCP server once the final client runtime is selected.
