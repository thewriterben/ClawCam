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

## Initial API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health. |
| `POST` | `/api/v1/devices` | Register or update a device. |
| `POST` | `/api/v1/events` | Ingest a schema-validated node event. |
| `POST` | `/api/v1/health` | Ingest node health telemetry. |
| `GET` | `/api/v1/detections/recent` | Return recent event summaries. |
| `GET` | `/api/v1/devices/{device_id}/health` | Return latest health for a device. |
