"""FastAPI application for the ClawCam gateway."""

from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hashlib
import uuid as _uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from clawcam_gateway.alerts.evaluator import AlertEvaluator
from clawcam_gateway.api.auth_dependency import (
    get_auth_context,
    require_admin,
    require_write,
)
from clawcam_gateway.api.dashboard import render_dashboard
from clawcam_gateway.auth import (
    AuthContext,
    SCOPES,
    auth_response_payload,
    generate_api_key,
    hash_api_key,
)
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.inference.pipeline import InferencePipeline
from clawcam_gateway.ingest.export import (
    csv_filename,
    export_detections_csv,
    export_events_csv,
)
from clawcam_gateway.ingest.validation import validate_device, validate_event, validate_health
from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool
from clawcam_gateway.mqtt_bridge.bridge import MQTTBridge
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.sync.cloud_store import get_cloud_store
from clawcam_gateway.sync.upload_worker import CloudUploadWorker


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
    pipeline = InferencePipeline(db=db, enabled=config.inference_enabled)
    cloud_store = get_cloud_store(config)
    cloud_worker = CloudUploadWorker(db=db, store=cloud_store)
    alert_evaluator = AlertEvaluator(db=db, default_webhook=config.alert_webhook_url)
    bridge = MQTTBridge(
        db=db,
        broker_host=config.mqtt_broker_host,
        broker_port=config.mqtt_broker_port,
        client_id=config.mqtt_client_id,
        mqtt_root=config.mqtt_topic_root,
        username=config.mqtt_username,
        password=config.mqtt_password,
    ) if config.mqtt_enabled else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if bridge is not None:
            bridge.start()
        yield
        if bridge is not None:
            bridge.stop()

    app = FastAPI(
        title="ClawCam Gateway",
        description="Offline-first field gateway for ClawCam wildlife monitoring deployments.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Make config, db, and the auth flag visible to FastAPI dependencies.
    app.state.config = config
    app.state.db = db
    app.state.auth_enabled = config.auth_enabled
    app.state.default_deployment_id = config.default_deployment_id

    @app.get("/health")
    def service_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "gateway_id": config.gateway_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "auth_enabled": config.auth_enabled,
        }

    # ── Deployments + API keys (Phase 7) ─────────────────────────────────

    @app.get("/api/v1/deployments")
    def list_deployments_endpoint(auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        """List deployments. Admin scope sees all; lower scopes see only their own."""
        deployments = db.list_deployments()
        if auth.scope != "admin":
            deployments = [d for d in deployments if d["deployment_id"] == auth.deployment_id]
        return {"ok": True, "deployments": deployments, "count": len(deployments)}

    @app.get("/api/v1/deployments/{deployment_id}")
    def get_deployment_endpoint(
        deployment_id: str, auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        if auth.scope != "admin" and deployment_id != auth.deployment_id:
            raise HTTPException(status_code=403, detail="cross-deployment access denied")
        deployment = db.get_deployment(deployment_id)
        if deployment is None:
            raise HTTPException(status_code=404, detail=f"unknown deployment: {deployment_id}")
        return {"ok": True, "deployment": deployment}

    @app.post("/api/v1/deployments")
    def create_deployment_endpoint(
        payload: Payload, auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        import uuid as _uuid_mod
        data = payload.data
        if not data.get("name"):
            raise HTTPException(status_code=400, detail="name is required")
        deployment_id = data.get("deployment_id") or f"dep-{_uuid_mod.uuid4().hex[:12]}"
        if db.get_deployment(deployment_id) is not None:
            raise HTTPException(status_code=409, detail=f"deployment_id exists: {deployment_id}")
        deployment = {
            "deployment_id": deployment_id,
            "name": data["name"],
            "profile": data.get("profile", "general"),
            "status": "active",
            "description": data.get("description"),
            "metadata": data.get("metadata", {}),
        }
        db.add_deployment(deployment)
        return {"ok": True, "deployment": db.get_deployment(deployment_id)}

    @app.patch("/api/v1/deployments/{deployment_id}")
    def update_deployment_endpoint(
        deployment_id: str, payload: Payload,
        auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        updated = db.update_deployment(deployment_id, payload.data)
        if not updated:
            raise HTTPException(status_code=404, detail=f"unknown deployment: {deployment_id}")
        return {"ok": True, "deployment": db.get_deployment(deployment_id)}

    @app.delete("/api/v1/deployments/{deployment_id}")
    def delete_deployment_endpoint(
        deployment_id: str, auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        if deployment_id == "default":
            raise HTTPException(status_code=400, detail="cannot delete the 'default' deployment")
        deleted = db.delete_deployment(deployment_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"unknown deployment: {deployment_id}")
        return {"ok": True, "deployment_id": deployment_id, "deleted": True}

    @app.get("/api/v1/api-keys")
    def list_api_keys_endpoint(
        deployment_id: str | None = None,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """List API keys. Plaintext tokens are never returned."""
        # Non-admins can only see their own deployment's keys.
        scope_filter = deployment_id
        if auth.scope != "admin":
            scope_filter = auth.deployment_id
        keys = db.list_api_keys(deployment_id=scope_filter)
        return {"ok": True, "keys": keys, "count": len(keys)}

    @app.post("/api/v1/api-keys")
    def create_api_key_endpoint(
        payload: Payload, auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        """Mint a new API key. The plaintext token is returned ONCE."""
        import uuid as _uuid_mod
        from datetime import datetime as _dt, timezone as _tz
        data = payload.data
        if not data.get("name"):
            raise HTTPException(status_code=400, detail="name is required")
        deployment_id = data.get("deployment_id", auth.deployment_id)
        if db.get_deployment(deployment_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown deployment: {deployment_id}")
        scope = data.get("scope", "read")
        if scope not in SCOPES:
            raise HTTPException(status_code=400, detail=f"scope must be one of {list(SCOPES)}")
        token = generate_api_key()
        key_id = f"key-{_uuid_mod.uuid4().hex[:12]}"
        now = _dt.now(_tz.utc).isoformat()
        db.add_api_key({
            "key_id": key_id,
            "deployment_id": deployment_id,
            "name": data["name"],
            "key_hash": hash_api_key(token),
            "scope": scope,
            "enabled": True,
            "expires_at": data.get("expires_at"),
        })
        return auth_response_payload(
            key_id=key_id,
            plaintext_key=token,
            name=data["name"],
            scope=scope,
            deployment_id=deployment_id,
            created_at=now,
            expires_at=data.get("expires_at"),
        )

    @app.post("/api/v1/api-keys/{key_id}/revoke")
    def revoke_api_key_endpoint(
        key_id: str, auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        revoked = db.revoke_api_key(key_id)
        if not revoked:
            raise HTTPException(status_code=404, detail=f"unknown key_id: {key_id}")
        return {"ok": True, "key_id": key_id, "revoked": True}

    @app.delete("/api/v1/api-keys/{key_id}")
    def delete_api_key_endpoint(
        key_id: str, auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        deleted = db.delete_api_key(key_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"unknown key_id: {key_id}")
        return {"ok": True, "key_id": key_id, "deleted": True}

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
        # Evaluate alert rules after inference completes
        background_tasks.add_task(alert_evaluator.evaluate, event_id, None)
        # Queue cloud upload alongside inference (noop when cloud is disabled)
        background_tasks.add_task(cloud_worker.queue_and_upload, dest, event_id)
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

    # ── Cloud sync (Phase 4) ─────────────────────────────────────────────

    @app.get("/api/v1/cloud/uploads")
    def cloud_upload_status(
        limit: int = 25,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Return cloud upload records with optional status filter."""
        safe_limit = max(1, min(limit, 100))
        uploads = db.list_cloud_uploads(limit=safe_limit, status=status)
        summary = db.get_cloud_upload_summary()
        return {
            "ok": True,
            "provider": cloud_store.provider,
            "cloud_enabled": config.cloud_enabled,
            "summary": summary,
            "uploads": uploads,
            "count": len(uploads),
        }

    # ── Alert rules (Phase 6) ────────────────────────────────────────────

    @app.post("/api/v1/alert-rules")
    def create_alert_rule(payload: Payload) -> dict[str, Any]:
        """Create a new alert rule. Returns the created rule with its rule_id."""
        import uuid as _uuid_mod
        from datetime import datetime as _dt, timezone as _tz
        data = payload.data
        if not data.get("name"):
            raise HTTPException(status_code=400, detail="name is required")
        rule = {
            "rule_id": f"rule-{_uuid_mod.uuid4().hex[:12]}",
            "name": data["name"],
            "label": data.get("label"),
            "min_confidence": float(data.get("min_confidence", 0.5)),
            "species_pattern": data.get("species_pattern"),
            "device_id": data.get("device_id"),
            "webhook_url": data.get("webhook_url") or config.alert_webhook_url,
            "enabled": bool(data.get("enabled", True)),
            "created_at": _dt.now(_tz.utc).isoformat(),
        }
        db.add_alert_rule(rule)
        return {"ok": True, "rule": rule}

    @app.get("/api/v1/alert-rules")
    def list_alert_rules_endpoint() -> dict[str, Any]:
        """Return all configured alert rules."""
        rules = db.list_alert_rules()
        return {"ok": True, "rules": rules, "count": len(rules)}

    @app.get("/api/v1/alert-rules/{rule_id}")
    def get_alert_rule(rule_id: str) -> dict[str, Any]:
        """Return a single alert rule by ID."""
        rule = db.get_alert_rule(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail=f"unknown rule_id: {rule_id}")
        return {"ok": True, "rule": rule}

    @app.patch("/api/v1/alert-rules/{rule_id}")
    def update_alert_rule(rule_id: str, payload: Payload) -> dict[str, Any]:
        """Partially update an alert rule (enabled/disabled, webhook_url, etc.)."""
        updated = db.update_alert_rule(rule_id, payload.data)
        if not updated:
            raise HTTPException(status_code=404, detail=f"unknown rule_id: {rule_id}")
        return {"ok": True, "rule_id": rule_id, "updated": list(payload.data.keys())}

    @app.delete("/api/v1/alert-rules/{rule_id}")
    def delete_alert_rule(rule_id: str) -> dict[str, Any]:
        """Delete an alert rule permanently."""
        deleted = db.delete_alert_rule(rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"unknown rule_id: {rule_id}")
        return {"ok": True, "rule_id": rule_id, "deleted": True}

    @app.get("/api/v1/alerts")
    def list_alerts(
        limit: int = 25,
        rule_id: str | None = None,
        delivery_status: str | None = None,
    ) -> dict[str, Any]:
        """Return recent fired alert events."""
        safe_limit = max(1, min(limit, 200))
        events = db.list_alert_events(
            limit=safe_limit,
            rule_id=rule_id,
            delivery_status=delivery_status,
        )
        return {"ok": True, "alerts": events, "count": len(events)}

    # ── Data export (Phase 5) ────────────────────────────────────────────

    @app.get("/api/v1/export/events.csv")
    def export_events(
        limit: int = 1000,
        device_id: str | None = None,
    ) -> StreamingResponse:
        """Download recent events as a CSV file."""
        safe_limit = max(1, min(limit, 10000))
        csv_text = export_events_csv(db, limit=safe_limit, device_id=device_id)
        filename = csv_filename("events")
        return StreamingResponse(
            iter([csv_text]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/export/detections.csv")
    def export_detections(
        limit: int = 1000,
        label: str | None = None,
        min_confidence: float = 0.0,
        species: str | None = None,
    ) -> StreamingResponse:
        """Download recent inference detections as a CSV file."""
        safe_limit = max(1, min(limit, 10000))
        csv_text = export_detections_csv(
            db,
            limit=safe_limit,
            label=label,
            min_confidence=min_confidence,
            species=species,
        )
        filename = csv_filename("detections")
        return StreamingResponse(
            iter([csv_text]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Cloud retry (Phase 5) ────────────────────────────────────────────

    @app.post("/api/v1/cloud/retry")
    def retry_failed_uploads(background_tasks: BackgroundTasks) -> dict[str, Any]:
        """Re-queue all failed cloud uploads for retry in the background."""
        failed = db.list_cloud_uploads(status="failed", limit=500)
        for upload in failed:
            media_path = Path(upload["media_path"])
            background_tasks.add_task(
                cloud_worker.queue_and_upload,
                media_path,
                upload.get("event_id"),
            )
        return {
            "ok": True,
            "retried": len(failed),
            "message": f"{len(failed)} failed upload(s) re-queued for retry.",
        }

    # ── Firmware OTA (Phase 3C) ───────────────────────────────────────────

    @app.post("/api/v1/firmware")
    async def upload_firmware(file: UploadFile) -> dict[str, Any]:
        """Upload a firmware .bin image. Returns build_id, sha256, and download URL.

        The node uses the download URL in the firmware_update command payload.
        Firmware binaries are served back at GET /api/v1/firmware/{build_id}/download.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="empty firmware file")

        sha256 = hashlib.sha256(content).hexdigest()
        build_id = _uuid.uuid4().hex[:16]
        original_name = file.filename or "firmware.bin"
        safe_name = f"{build_id}_{original_name}"

        fw_dir = config.media_dir / "firmware"
        fw_dir.mkdir(parents=True, exist_ok=True)
        dest = fw_dir / safe_name
        dest.write_bytes(content)

        # Extract version from filename if present (e.g. "clawcam-node-0.2.0.bin")
        stem = Path(original_name).stem
        version = stem.split("-")[-1] if "-" in stem else stem

        db.add_firmware_build(build_id, version, safe_name, sha256, len(content))
        return {
            "ok": True,
            "build_id": build_id,
            "version": version,
            "sha256": sha256,
            "size_bytes": len(content),
            "download_url": f"/api/v1/firmware/{build_id}/download",
        }

    @app.get("/api/v1/firmware")
    def list_firmware() -> dict[str, Any]:
        """List all uploaded firmware builds."""
        builds = db.list_firmware_builds()
        return {"ok": True, "builds": builds, "count": len(builds)}

    @app.get("/api/v1/firmware/{build_id}")
    def get_firmware_build(build_id: str) -> dict[str, Any]:
        """Return metadata for a specific firmware build."""
        build = db.get_firmware_build(build_id)
        if build is None:
            raise HTTPException(status_code=404, detail=f"unknown build_id: {build_id}")
        return {"ok": True, "build": build}

    @app.get("/api/v1/firmware/{build_id}/download")
    def download_firmware(build_id: str) -> FileResponse:
        """Serve the raw firmware binary for a node OTA download."""
        build = db.get_firmware_build(build_id)
        if build is None:
            raise HTTPException(status_code=404, detail=f"unknown build_id: {build_id}")
        fw_path = config.media_dir / "firmware" / build["filename"]
        if not fw_path.exists():
            raise HTTPException(status_code=404, detail="firmware file not found on disk")
        return FileResponse(
            path=str(fw_path),
            media_type="application/octet-stream",
            filename=build["filename"],
        )

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
                {"name": "list_firmware_builds", "approval_required": False},
                {"name": "get_cloud_sync_status", "approval_required": False},
                {"name": "export_detections_csv", "approval_required": False},
                {"name": "list_alert_rules", "approval_required": False},
                {"name": "list_recent_alerts", "approval_required": False},
                {"name": "capture_now", "approval_required": True},
                {"name": "create_alert_rule", "approval_required": True},
                {"name": "apply_config_patch", "approval_required": True},
                {"name": "queue_firmware_update", "approval_required": True},
            ]
        }

    @app.post("/api/v1/tools/{tool_name}")
    def call_tool(tool_name: str, request: ToolRequest) -> dict[str, Any]:
        result = dispatch_tool(
            tool_name, request.arguments,
            database_path=config.database_path,
            mqtt_bridge=bridge,
        )
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

    # Inference summary
    recent_detections = db.list_inference_results(limit=safe_limit)
    detection_label_counts: Counter[str] = Counter(
        r["top_label"] for r in recent_detections if r.get("top_label")
    )
    detection_species_counts: Counter[str] = Counter(
        r["top_species"] for r in recent_detections if r.get("top_species")
    )

    # Cloud summary
    cloud_summary = db.get_cloud_upload_summary()

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
        "recent_detections": recent_detections,
        "detection_label_counts": dict(detection_label_counts),
        "detection_species_counts": dict(detection_species_counts),
        "cloud_summary": cloud_summary,
        "cloud_enabled": config.cloud_enabled,
    }


app = create_app()
