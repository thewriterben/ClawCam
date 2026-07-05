# Oh-Ben-Claw Adapter

`clawcam_adapter.py` is the Oh-Ben-Claw-side adapter for the ClawCam gateway.
It launches the gateway's MCP stdio server (`clawcam_gateway.mcp_server.stdio_server`)
as a subprocess, discovers the tool catalog via `tools/list`, and registers the
tools with the brain's registry under the gateway's approval policy.

## What it provides

- **Dual protocol modes** — `legacy-2024` and `stateless-2026` (SEP-2575
  `_meta`), matching the gateway server; mode is negotiated at startup.
- **Approval policy** — 35 read tools auto-approved; 11 mutating tools always
  prompt. Approval scopes: per-call, per-session, or forever; plan mode can
  bound arguments (e.g. cap `limit`) instead of blocking outright.
- **Catalog sync** — the tool partition is derived from the gateway's
  `TOOL_DEFINITIONS` + `APPROVAL_REQUIRED_TOOLS`; drift is caught by
  `tests/gateway/test_tool_catalog_ssot.py` (the test imports this adapter —
  put this directory on `PYTHONPATH`).

Mutating tools queue real work: `capture_now` validates the device's
`cap_clawcam_camera_trap` capability and inserts a `pending_commands` row
(pushed immediately over MQTT when the bridge is connected).

## Run the bridge manually

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.mcp_server.stdio_server --db ../clawcam_gateway.db
```

## Configuration

`examples/clawcam-mcp-stdio.toml` mirrors Oh-Ben-Claw's `McpServerConfig`
fields (`transport`, `command`, `args`, `url`, `token`, `env`). The broader
integration guide lives at `docs/integration/oh-ben-claw-mcp.md`; the full
tool catalog at `docs/standards/mcp-tools.md`.
