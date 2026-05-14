"""FastAPI application for the ClawCam gateway."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from clawcam_gateway.api.dashboard import render_dashboard
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.pipeline import InferencePipeline
from clawcam_gateway.ingest.validation import validate_device, validate_event, validate_health
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.storage.database import GatewayDatabase


class Payload(BaseModel):
    """Generic JSON payload wrapper used by scaffold endpoints."""

    data: dict[str, Any] = Field(default_factory=dict)


class ToolRequest(BaseModel):
    """HTTP wrapper for MCP-style ClawCam tool dispatch."""

    arguments: dict[str, Any] = Field(default_factory=dict)


class CommandAck(BaseModel):
    """Node acknowledgement for a dispatched command."""

    status: str  # "executed" | "failed" | "skipped"
    result: dict[str, Any] = Field(default_factory=dict)


def create_app(config: GatewayConfig | None = None) -> FastAPI:
    config = config or GatewayConfig.from_env()
    db = GatewayDatabase(config.database_path)
    pipeline = InferencePipeline(
        db=db,
        enabled=config.inference_enabled,
    )

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

    # ── Node command transport (Phase 2) ──────────────────────────────────

    @app.get("/api/v1/commands/{device_id}/pending")
    def get_pending_commands(device_id: str, limit: int = 10) -> dict[str, Any]:
        """Return queued commands for a node. Called by the node on each wake cycle."""
        if db.get_device(device_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        safe_limit = max(1, min(limit, 50))
        commands = db.list_pending_commands(device_id=device_id, status="queued")[:safe_limit]
        # Mark returned commands as "delivered" so they aren't re-sent on the next poll
        for cmd in commands:
            db.update_command_status(cmd["command_id"], "delivered")
        return {"ok": True, "device_id": device_id, "commands": commands, "count": len(commands)}

    @app.post("/api/v1/commands/{command_id}/ack")
    def ack_command(command_id: str, ack: CommandAck) -> dict[str, Any]:
        """Node reports execution result for a delivered command."""
        allowed = {"executed", "failed", "skipped"}
        if ack.status not in allowed:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")
        updated = db.update_command_status(command_id, ack.status, result=ack.result)
        if not updated:
            raise HTTPException(status_code=404, detail=f"unknown command_id: {command_id}")
        return {"ok": True, "command_id": command_id, "status": ack.status}

    @app.get("/api/v1/devices/{device_id}/capabilities")
    def device_capabilities(device_id: str) -> dict[str, Any]:
        """Return the capability groups declared by a node."""
        caps = db.get_device_capabilities(device_id)
        if db.get_device(device_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        return {"ok": True, "device_id": device_id, "capabilities": caps}

    # ── Inference (Phase 3) ───────────────────────────────────────────────

    @app.post("/api/v1/media/{event_id}")
    async def upload_media(
        event_id: str,
        file: UploadFile,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Accept a JPEG/PNG image from a node and trigger inference in the background.

        The event must already exist (registered via POST /api/v1/events).
        Inference runs asynchronously so this endpoint returns immediately.
        """
        if db.get_inference_result(event_id) is not None and \
                db.get_inference_result(event_id).get("model_name") != "mock_detector":
            # Already processed; accept the upload but skip re-inference
            return {"ok": True, "event_id": event_id, "inference": "already_processed"}

        # Save the uploaded file into the configured media directory
        config.media_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "image.jpg").suffix or ".jpg"
        dest = config.media_dir / f"{event_id}{suffix}"
        content = await file.read()
        dest.write_bytes(content)

        # Run inference in the background (non-blocking)
        background_tasks.add_task(pipeline.run, event_id, str(dest))
        return {"ok": True, "event_id": event_id, "media_path": str(dest), "inference": "queued"}

    @app.get("/api/v1/events/{event_id}/inference")
    def get_event_inference(event_id: str) -> dict[str, Any]:
        """Return the inference result for a specific event."""
        result = db.get_inference_result(event_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"no inference result for event {event_id}")
        return {"ok": True, "result": result}

    @app.get("/api/v1/inference/recent")
    def recent_inference(
        limit: int = 25,
        label: str | None = None,
        min_confidence: float = 0.0,
        species: str | None = None,
    ) -> dict[str, Any]:
        """List recent inference results with optional filters."""
        safe_limit = max(1, min(limit, 100))
        results = db.list_inference_results(
            limit=safe_limit,
            label=label,
            min_confidence=min_confidence,
            species=species,
        )
        return {"ok": True, "results": results, "count": len(results)}

    # ── Tools ─────────────────────────────────────────────────────────────

    @app.get("/api/v1/tools")
    def list_tools() -> dict[str, Any]:
        return {
            "tools": [
                {"name": "get_recent_detections", "approval_required": False},
                {"name": "get_node_health", "approval_required": False},
                {"name": "generate_daily_summary", "approval_required": False},
                {"name": "list_pending_commands", "approval_required": False},
                {"name": "list_capabilities", "approval_required": False},
                {"name": "get_inference_results", "approval_required": False},
                {"name": "list_species_detections", "approval_required": False},
                {"name": "capture_now", "approval_required": True},
                {"name": "apply_config_patch", "approval_required": True},
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
