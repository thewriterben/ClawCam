"""FastAPI application for the ClawCam gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.ingest.validation import validate_device, validate_event, validate_health
from clawcam_gateway.storage.database import GatewayDatabase


class Payload(BaseModel):
    """Generic JSON payload wrapper used by scaffold endpoints."""

    data: dict[str, Any] = Field(default_factory=dict)


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

    return app


app = create_app()
