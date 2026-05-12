# ClawCam Gateway

The ClawCam gateway is the offline-first field station for node ingest, validation, storage, local APIs, diagnostics, and agent-compatible tools.

## Current Status

This is an initial scaffold. It includes a FastAPI application, SQLite persistence, and JSON-schema validation hooks. It is intended to become the first working vertical slice for ClawCam.

## Run Locally

```bash
cd gateway
python -m clawcam_gateway.main
```

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `CLAWCAM_DB` | `clawcam_gateway.db` | SQLite database path. |
| `CLAWCAM_MEDIA_DIR` | `media` | Local media cache directory. |
| `CLAWCAM_HOST` | `0.0.0.0` | API bind host. |
| `CLAWCAM_PORT` | `8080` | API port. |
| `CLAWCAM_GATEWAY_ID` | `local-gateway` | Gateway identity. |

## Phase 1 Simulator Flow

Generate deterministic sample payloads without hardware:

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.simulator.cli --output ../samples/node-simulator
```

Import either the hand-authored samples or generated simulator payloads into a local database:

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.ingest.cli import-sample ../samples/payloads --db ../clawcam_gateway.db
PYTHONPATH=. python -m clawcam_gateway.ingest.cli import-sample ../samples/node-simulator --db ../clawcam_gateway.db
```

Use the Python tool functions directly from tests or adapter code:

```python
from clawcam_gateway.tools import ToolContext, get_recent_detections, get_node_health

context = ToolContext(database_path="../clawcam_gateway.db")
print(get_recent_detections(context, limit=10))
print(get_node_health(context, "node-001"))
```

Run the gateway and open the local dashboard:

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.main
# Then open http://localhost:8080/dashboard
```

Call the HTTP tool-dispatch endpoint:

```bash
curl -X POST http://localhost:8080/api/v1/tools/get_recent_detections \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"limit":10}}'
```

## Initial API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health. |
| `POST` | `/api/v1/devices` | Register or update a device. |
| `POST` | `/api/v1/events` | Ingest a schema-validated node event. |
| `POST` | `/api/v1/health` | Ingest node health telemetry. |
| `GET` | `/api/v1/detections/recent` | Return recent event summaries. |
| `GET` | `/api/v1/devices/{device_id}/health` | Return latest health for a device. |
| `GET` | `/api/v1/tools` | List currently exposed ClawCam gateway tools. |
| `POST` | `/api/v1/tools/{tool_name}` | Dispatch a ClawCam gateway tool over HTTP. |
| `GET` | `/api/v1/dashboard` | Return dashboard summary data as JSON. |
| `GET` | `/dashboard` | Render the no-build local HTML dashboard. |
