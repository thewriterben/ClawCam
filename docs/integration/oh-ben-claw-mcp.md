# Oh-Ben-Claw Integration Through the ClawCam Gateway Bridge

ClawCam exposes its first agent-facing tool surface through a lightweight MCP-compatible stdio bridge. This lets Oh-Ben-Claw and similar agent runtimes query gateway detections, node health, and daily summaries without coupling directly to ClawCam’s internal Python package.

## Integration Shape

The integration is intentionally layered. ClawCam remains the field data system of record. Oh-Ben-Claw connects as a supervised operations brain and calls read-only tools automatically while approval-gated tools remain blocked or require explicit operator approval.

| Layer | Responsibility |
|---|---|
| ClawCam Gateway | Stores devices, events, health records, media references, and future observations. |
| ClawCam MCP-Compatible Bridge | Exposes gateway tools over newline-delimited JSON-RPC stdio. |
| Oh-Ben-Claw Brain | Uses the discovered tools for wildlife summaries, node diagnostics, and operational planning. |

## Example Configuration

Use `brain/oh-ben-claw-adapter/examples/clawcam-mcp-stdio.toml` as the integration template. The `mcp_servers.clawcam_gateway` block mirrors Oh-Ben-Claw’s `McpServerConfig` fields: `transport`, `command`, `args`, `url`, `token`, and `env`.

## Local Demo Flow

Generate and import simulator data first:

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.simulator.cli --output ../samples/node-simulator
PYTHONPATH=. python -m clawcam_gateway.ingest.cli import-sample ../samples/node-simulator --db ../clawcam_gateway.db
```

Start the ClawCam stdio bridge when the agent runtime launches it:

```bash
PYTHONPATH=. python -m clawcam_gateway.mcp_server.stdio_server --db ../clawcam_gateway.db
```

The bridge supports `initialize`, `tools/list`, `tools/call`, and `ping`. Read-only tools currently include `get_recent_detections`, `get_node_health`, and `generate_daily_summary`.

## Tool Policy

| Tool | Default Policy | Reason |
|---|---|---|
| `get_recent_detections` | Auto-allowed | Read-only field data query. |
| `get_node_health` | Auto-allowed | Read-only diagnostics query. |
| `generate_daily_summary` | Auto-allowed | Analysis over stored local records. |
| `capture_now` | Approval required | Can affect wildlife, battery, storage, and privacy. |
| `apply_config_patch` | Approval required | Mutates field-device behavior. |

## Next Adapter Step

The next implementation task is to add a small Oh-Ben-Claw-side adapter or example loader that reads this config, launches the stdio bridge, calls `tools/list`, and registers the returned ClawCam tools with the Oh-Ben-Claw tool registry.
