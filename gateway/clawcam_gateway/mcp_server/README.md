# ClawCam Gateway MCP Server

`stdio_server.py` is a dual-mode MCP stdio server exposing the full gateway
tool surface: **46 tools — 35 auto-approved reads, 11 approval-gated writes**
(see `docs/standards/mcp-tools.md`, generated from `tool_catalog()`).

It speaks two protocol lifecycles and negotiates per client:

| Mode | Lifecycle |
|---|---|
| `legacy-2024` | Classic stateful `initialize` → `tools/list` → `tools/call` |
| `2026-07-28` | Stateless SEP-2575 (`_meta` carried per call) |

`TOOL_DEFINITIONS` + `APPROVAL_REQUIRED_TOOLS` in this package are the single
source of truth: the REST catalog (`GET /api/v1/tools`), the dispatcher
(`tool_dispatch.py`), and the Oh-Ben-Claw adapter
(`brain/oh-ben-claw-adapter/clawcam_adapter.py`) all derive from it, and
`tests/gateway/test_tool_catalog_ssot.py` enforces the sync.

## Run the server

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.mcp_server.stdio_server --db ../clawcam_gateway.db
```

Newline-delimited JSON-RPC over stdio. Supported methods: `initialize`,
`tools/list`, `tools/call`, `ping`.

## Approval model

Mutating tools (`capture_now`, `apply_config_patch`, `queue_firmware_update`,
`set_device_state`, `create_alert_rule`, …) are approval-gated: the
Oh-Ben-Claw adapter always prompts (call/session/forever scopes, plan-mode
argument bounds), and the REST bridge requires an API key with `write` scope
when auth is enabled. Read tools are auto-approved.

## Example calls

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_recent_detections","arguments":{"limit":10}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_review_queue","arguments":{"limit":5}}}
```

## Notes

- No MCP *resources* are implemented — tools only.
- Tool failures return structured `{"ok": false, "error": ...}` results and
  are recorded in the `tool_call_audit` table; the dispatcher never raises.
- On July 28, 2026 the default `protocol_mode` flips to `stateless-2026`
  (see `docs/STATUS.md`, Phase 13).
