# ClawCam MCP-Compatible Gateway Server

ClawCam exposes its gateway tools through a lightweight JSON-RPC stdio server that follows the practical shape of Model Context Protocol tool interactions. This first implementation supports `initialize`, `tools/list`, `tools/call`, and `ping` so agent clients can discover and invoke gateway tools without depending on the HTTP API.

## Current Status

This is a **Phase 1 MCP-compatible interface**, not a full production MCP server. It wraps the same gateway tool functions used by the HTTP tool endpoint and the Python dispatcher. It is intentionally dependency-light so it can run on field gateways without adding a large runtime surface.

## Run the Server

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.mcp_server.stdio_server --db ../clawcam_gateway.db
```

The server reads newline-delimited JSON-RPC messages from standard input and writes newline-delimited JSON-RPC responses to standard output.

## Supported Methods

| Method | Purpose |
|---|---|
| `initialize` | Returns protocol version, server info, and tool capability metadata. |
| `tools/list` | Lists available ClawCam gateway tools and JSON input schemas. |
| `tools/call` | Invokes one gateway tool with JSON arguments. |
| `ping` | Returns an empty success response. |

## Available Tools

| Tool | Purpose | Phase 1 Status |
|---|---|---|
| `get_recent_detections` | Query recent gateway event/detection records. | Working |
| `get_node_health` | Query latest health for a device. | Working |
| `generate_daily_summary` | Generate a small structured summary from stored events. | Working scaffold |
| `capture_now` | Request a manual capture from a reachable node. | Approval-gated placeholder |
| `apply_config_patch` | Apply a configuration patch. | Approval-gated placeholder |

## Example JSON-RPC Messages

Initialize:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
```

List tools:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

Call `get_recent_detections`:

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_recent_detections","arguments":{"limit":10}}}
```

Call `get_node_health`:

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_node_health","arguments":{"device_id":"node-001"}}}
```

## Oh-Ben-Claw Integration Direction

Oh-Ben-Claw can treat this server as the first ClawCam tool source. The brain should launch the stdio server with the target gateway database path, run `tools/list`, and call `tools/call` for read-only operations. Configuration, capture, publication, deletion, and firmware operations must remain approval-gated until the ClawCam policy layer is implemented.

## Next MCP Step

The next step is to add a true SDK-backed MCP server once the target client runtime is chosen. This lightweight server provides the shared tool definitions, JSON schemas, tests, and behavior that the SDK-backed version should preserve.
