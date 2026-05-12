"""FastAPI application for the ClawCam gateway."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from clawcam_gateway.api.dashboard import render_dashboard
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.ingest.validation import validate_device, validate_event, validate_health
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.storage.database import GatewayDatabase


class Payload(BaseModel):
    """Generic JSON payload wrapper used by scaffold endpoints."""

    data: dict[str, Any] = Field(default_factory=dict)


class ToolRequest(BaseModel):
    """HTTP wrapper for MCP-style ClawCam tool dispatch."""

    arguments: dict[str, Any] = Field(default_factory=dict)


def create_app(config: GatewayConfig | None = None) -> FastAPI:
    config = config or GatewayConfig.from_env()
    db = GatewayDatabase(config.database_path)

    app = FastAPI(
        title="ClawCam Gateway",
        description="Offline-first field gateway for ClawCam wildlife monitoring deployments.",
        version="0.1.0",
    )

    @app.get("/health")
    def service_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "gateway_id": config.gateway_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/api/v1/devices")
    def register_device(payload: Payload) -> dict[str, Any]:
        try:
            validate_device(payload.data)
            db.upsert_device(payload.data)
        except Exception as exc:  # noqa: BLE001 - API returns validation details
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "device_id": payload.data["device_id"]}

    @app.get("/api/v1/devices")
    def list_devices() -> dict[str, Any]:
        devices = db.list_devices()
        return {"devices": devices, "count": len(devices)}

    @app.post("/api/v1/events")
    def ingest_event(payload: Payload) -> dict[str, Any]:
        try:
            validate_event(payload.data)
            if db.get_device(payload.data["device_id"]) is None:
                raise ValueError(f"unknown device_id: {payload.data['device_id']}")
            db.add_event(payload.data)
        except Exception as exc:  # noqa: BLE001 - API returns validation details
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "event_id": payload.data["event_id"]}

    @app.post("/api/v1/health")
    def ingest_health(payload: Payload) -> dict[str, Any]:
        try:
            validate_health(payload.data)
            if db.get_device(payload.data["device_id"]) is None:
                raise ValueError(f"unknown device_id: {payload.data['device_id']}")
            db.add_health(payload.data)
        except Exception as exc:  # noqa: BLE001 - API returns validation details
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "device_id": payload.data["device_id"]}

    @app.get("/api/v1/detections/recent")
    def recent_detections(limit: int = 25) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        return {"detections": db.recent_events(limit=limit), "limit": limit}

    @app.get("/api/v1/devices/{device_id}/health")
    def device_health(device_id: str) -> dict[str, Any]:
        health = db.latest_health(device_id)
        if health is None:
            raise HTTPException(status_code=404, detail="no health record found")
        return health

    @app.get("/api/v1/tools")
    def list_tools() -> dict[str, Any]:
        return {
            "tools": [
                {"name": "get_recent_detections", "approval_required": False},
                {"name": "get_node_health", "approval_required": False},
                {"name": "generate_daily_summary", "approval_required": False},
                {"name": "capture_now", "approval_required": True, "implemented": False},
                {"name": "apply_config_patch", "approval_required": True, "implemented": False},
            ]
        }

    @app.post("/api/v1/tools/{tool_name}")
    def call_tool(tool_name: str, request: ToolRequest) -> dict[str, Any]:
        result = dispatch_tool(tool_name, request.arguments, database_path=config.database_path)
        if not result.get("ok", False) and result.get("error", "").startswith("unknown"):
            raise HTTPException(status_code=404, detail=result)
        return result

    @app.get("/api/v1/dashboard")
    def dashboard_data(limit: int = 25) -> dict[str, Any]:
        return _dashboard_payload(db, config, limit)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(limit: int = 25) -> HTMLResponse:
        return HTMLResponse(render_dashboard(_dashboard_payload(db, config, limit)))

    return app


def _dashboard_payload(db: GatewayDatabase, config: GatewayConfig, limit: int = 25) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    devices = db.list_devices()
    events = db.recent_events(limit=safe_limit)
    health_by_device = {
        device["device_id"]: db.latest_health(device["device_id"])
        for device in devices
    }
    event_counts = Counter(event.get("event_type", "unknown") for event in events)
    labels: Counter[str] = Counter()
    for event in events:
        for classification in event.get("classifications", []):
            labels[classification.get("label", "unknown")] += 1
    return {
        "gateway_id": config.gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "device_count": len(devices),
        "event_count": len(events),
        "devices": devices,
        "recent_events": events,
        "health_by_device": health_by_device,
        "event_counts": dict(event_counts),
        "label_counts": dict(labels),
    }


app = create_app()
