"""FastAPI application for the ClawCam gateway."""

from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hashlib
import re
import uuid as _uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from clawcam_gateway.alerts.evaluator import AlertEvaluator
from clawcam_gateway.audio import AudioPipeline
from clawcam_gateway.api.auth_dependency import (
    get_auth_context,
    require_admin,
    require_write,
)
from clawcam_gateway.api.dashboard import render_dashboard
from clawcam_gateway.api.ops_dashboard import render_ops_dashboard
from clawcam_gateway.auth import (
    AuthContext,
    SCOPE_ADMIN,
    SCOPE_WRITE,
    SCOPES,
    ScopeRequired,
    auth_response_payload,
    generate_api_key,
    hash_api_key,
)
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.scheduler import (
    ACTION_TYPES,
    ScheduleEngine,
    is_valid_action,
)
from clawcam_gateway.inference.orchestrator import InferenceOrchestrator
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


# Upload safety limits and filename validation (SSRF/traversal/DoS hardening).
MAX_MEDIA_BYTES = 50 * 1024 * 1024       # 50 MB cap for image/audio uploads
MAX_FIRMWARE_BYTES = 32 * 1024 * 1024    # 32 MB cap for firmware .bin uploads
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _safe_path_component(value: str) -> bool:
    """True if *value* is a safe single path component (no traversal)."""
    return bool(_SAFE_ID_RE.match(value)) and ".." not in value and "/" not in value and "\\" not in value


def _safe_suffix(filename: str | None, allowed: tuple[str, ...], default: str) -> str:
    """Return a lowercased extension from *filename* if in *allowed*, else *default*."""
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in allowed else default


def _deployment_scope(auth: AuthContext) -> str | None:
    """Tenant filter for reads: None (all) for admin or auth-disabled, else own deployment."""
    return None if auth.scope == SCOPE_ADMIN else auth.deployment_id


def _check_device_access(db, auth: AuthContext, device_id: str) -> None:
    """403 if a non-admin caller reads a device in another deployment (missing -> let 404 stand)."""
    scope = _deployment_scope(auth)
    if scope is None:
        return
    dep = db.deployment_for_device(device_id)
    if dep is not None and dep != scope:
        raise HTTPException(status_code=403, detail="forbidden: resource belongs to another deployment")


def _check_resource_deployment(auth: AuthContext, resource_deployment: str | None) -> None:
    """403 if a non-admin caller touches a resource in another deployment."""
    scope = _deployment_scope(auth)
    if scope is not None and resource_deployment is not None and resource_deployment != scope:
        raise HTTPException(status_code=403, detail="forbidden: resource belongs to another deployment")


def _resolve_target_deployment(auth: AuthContext, requested: str | None) -> str:
    """Deployment a new resource lands in; non-admins may only use their own."""
    if requested is None:
        return auth.deployment_id
    if _deployment_scope(auth) is not None and requested != auth.deployment_id:
        raise HTTPException(status_code=403, detail="forbidden: cannot create resources in another deployment")
    return requested


def _check_event_access(db, auth: AuthContext, event_id: str) -> None:
    """403 if a non-admin caller reads an event in another deployment (missing -> let 404 stand)."""
    scope = _deployment_scope(auth)
    if scope is None:
        return
    dep = db.deployment_for_event(event_id)
    if dep is not None and dep != scope:
        raise HTTPException(status_code=403, detail="forbidden: resource belongs to another deployment")


def create_app(config: GatewayConfig | None = None) -> FastAPI:
    config = config or GatewayConfig.from_env()
    db = GatewayDatabase(config.database_path)
    pipeline = InferencePipeline(db=db, enabled=config.inference_enabled,
                                 weights_path=config.inference_weights_path)
    inference_orchestrator = InferenceOrchestrator(db=db, enabled=config.inference_enabled)
    cloud_store = get_cloud_store(config)
    cloud_worker = CloudUploadWorker(db=db, store=cloud_store)
    alert_evaluator = AlertEvaluator(db=db, default_webhook=config.alert_webhook_url,
                                     allow_private_hosts=config.webhook_allow_private_hosts,
                                     dedup_window_s=config.alert_dedup_window_s,
                                     min_severity=config.alert_min_severity,
                                     zone_min_coverage=config.alert_zone_min_coverage)
    schedule_engine = ScheduleEngine(db=db, allow_private_hosts=config.webhook_allow_private_hosts,
                                     tick_interval_s=config.scheduler_tick_interval_s)
    audio_pipeline = AudioPipeline(db=db, enabled=config.audio_enabled)
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
        if config.scheduler_enabled:
            schedule_engine.start()
        yield
        if config.scheduler_enabled:
            schedule_engine.stop()
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

    # ── Detection zones (Phase 10) ────────────────────────────────────────

    @app.get("/api/v1/zones")
    def list_zones_endpoint(
        device_id: str | None = None,
        deployment_id: str | None = None,
        enabled_only: bool = False,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        scope_filter = deployment_id
        if auth.scope != "admin":
            scope_filter = auth.deployment_id
        zones = db.list_detection_zones(
            device_id=device_id, deployment_id=scope_filter,
            enabled_only=enabled_only,
        )
        return {"ok": True, "zones": zones, "count": len(zones)}

    @app.get("/api/v1/zones/{zone_id}")
    def get_zone_endpoint(
        zone_id: str, auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        zone = db.get_detection_zone(zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail=f"unknown zone: {zone_id}")
        _check_resource_deployment(auth, zone.get("deployment_id"))
        return {"ok": True, "zone": zone}

    @app.post("/api/v1/zones")
    def create_zone_endpoint(
        payload: Payload, auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        import uuid as _uuid_mod
        from clawcam_gateway.zones import is_valid_polygon, is_valid_zone_action
        data = payload.data
        for field in ("device_id", "name", "polygon", "action"):
            if field not in data:
                raise HTTPException(status_code=400, detail=f"{field} is required")
        if not is_valid_polygon(data["polygon"]):
            raise HTTPException(
                status_code=400,
                detail="polygon must be a list of >=3 [x, y] points with 0 <= x,y <= 1",
            )
        if not is_valid_zone_action(data["action"]):
            raise HTTPException(
                status_code=400,
                detail="action must be one of: alert, record, ignore, privacy_mask",
            )
        if db.get_device(data["device_id"]) is None:
            raise HTTPException(status_code=404, detail=f"unknown device: {data['device_id']}")
        zone_id = data.get("zone_id") or f"zone-{_uuid_mod.uuid4().hex[:12]}"
        zone = {
            "zone_id": zone_id,
            "device_id": data["device_id"],
            "deployment_id": _resolve_target_deployment(auth, data.get("deployment_id")),
            "name": data["name"],
            "polygon": data["polygon"],
            "action": data["action"],
            "priority": int(data.get("priority", 100)),
            "enabled": bool(data.get("enabled", True)),
        }
        db.add_detection_zone(zone)
        return {"ok": True, "zone": db.get_detection_zone(zone_id)}

    @app.patch("/api/v1/zones/{zone_id}")
    def update_zone_endpoint(
        zone_id: str, payload: Payload,
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        from clawcam_gateway.zones import is_valid_polygon, is_valid_zone_action
        existing = db.get_detection_zone(zone_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"unknown zone: {zone_id}")
        _check_resource_deployment(auth, existing.get("deployment_id"))
        updates = payload.data
        if "polygon" in updates and not is_valid_polygon(updates["polygon"]):
            raise HTTPException(status_code=400, detail="invalid polygon")
        if "action" in updates and not is_valid_zone_action(updates["action"]):
            raise HTTPException(status_code=400, detail="invalid action")
        ok = db.update_detection_zone(zone_id, updates)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown zone: {zone_id}")
        return {"ok": True, "zone": db.get_detection_zone(zone_id)}

    @app.delete("/api/v1/zones/{zone_id}")
    def delete_zone_endpoint(
        zone_id: str, auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        existing = db.get_detection_zone(zone_id)
        if existing is not None:
            _check_resource_deployment(auth, existing.get("deployment_id"))
        ok = db.delete_detection_zone(zone_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown zone: {zone_id}")
        return {"ok": True, "zone_id": zone_id, "deleted": True}

    # ── Detector chains (Phase 12) ────────────────────────────────────────

    @app.get("/api/v1/detectors")
    def list_registered_detectors() -> dict[str, Any]:
        """Return the registry of detectors known to the gateway."""
        from clawcam_gateway.inference.registry import get_registry
        reg = get_registry()
        return {
            "ok": True,
            "all_detectors": reg.names(),
            "available_detectors": reg.available_names(),
        }

    @app.get("/api/v1/devices/{device_id}/detector-chain")
    def get_device_detector_chain(device_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        _check_device_access(db, auth, device_id)
        chain = inference_orchestrator.chain_for_device(device_id)
        device = db.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        return {
            "ok": True,
            "device_id": device_id,
            "profile": device.get("profile"),
            "chain": chain,
            "override_set": "detector_chain" in device,
        }

    @app.patch("/api/v1/devices/{device_id}/detector-chain")
    def set_device_detector_chain_endpoint(
        device_id: str, payload: Payload,
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        chain = payload.data.get("chain")
        if chain is not None and not isinstance(chain, list):
            raise HTTPException(status_code=400, detail="chain must be a list of detector names or null")
        ok = db.set_device_detector_chain(device_id, chain)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        return {"ok": True, "device_id": device_id, "chain": chain}

    @app.get("/api/v1/events/{event_id}/inference/chain")
    def get_event_inference_chain(event_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        _check_event_access(db, auth, event_id)
        results = db.list_inference_results_for_event(event_id)
        return {"ok": True, "event_id": event_id, "results": results, "count": len(results)}

    # ── Audio pipeline (Phase 11) ─────────────────────────────────────────

    @app.post("/api/v1/audio/{event_id}")
    async def upload_audio(
        event_id: str,
        file: UploadFile,
        background_tasks: BackgroundTasks,
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        """Accept a WAV/OGG/MP3 from a node and run classifiers in the background."""
        event_row = db.get_event(event_id)
        if event_row is None:
            raise HTTPException(status_code=404, detail=f"unknown event: {event_id}")

        if not _safe_path_component(event_id):
            raise HTTPException(status_code=400, detail="invalid event_id")
        audio_dir = config.media_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        suffix = _safe_suffix(file.filename, (".wav", ".ogg", ".mp3", ".flac"), ".wav")
        content = await file.read()
        if len(content) > MAX_MEDIA_BYTES:
            raise HTTPException(status_code=413, detail="audio upload exceeds size limit")
        dest = (audio_dir / f"{event_id}{suffix}").resolve()
        if not dest.is_relative_to(audio_dir.resolve()):
            raise HTTPException(status_code=400, detail="invalid audio path")
        dest.write_bytes(content)

        audio_id = db.add_audio_upload({
            "event_id": event_id,
            "device_id": event_row.get("device_id"),
            "path": str(dest),
            "format": suffix.lstrip("."),
            "size_bytes": len(content),
        })

        background_tasks.add_task(audio_pipeline.run, audio_id, str(dest), event_id)
        # Evaluate alert rules against the acoustic classifications once stored.
        background_tasks.add_task(
            alert_evaluator.evaluate_audio, event_id, event_row.get("device_id"), audio_id,
        )
        return {
            "ok": True,
            "audio_id": audio_id,
            "event_id": event_id,
            "path": str(dest),
            "size_bytes": len(content),
            "classifier": audio_pipeline.classifier_name,
        }

    @app.get("/api/v1/audio/{event_id}/classifications")
    def get_event_audio_classifications(event_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        _check_event_access(db, auth, event_id)
        classifications = db.list_audio_classifications(event_id=event_id)
        uploads = db.list_audio_uploads(event_id=event_id)
        return {
            "ok": True,
            "event_id": event_id,
            "uploads": uploads,
            "classifications": classifications,
            "count": len(classifications),
        }

    @app.get("/api/v1/audio/recent")
    def recent_audio_classifications(
        limit: int = 25,
        label: str | None = None,
        species: str | None = None,
        min_confidence: float = 0.0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 200))
        results = db.list_audio_classifications(
            label=label, species=species,
            min_confidence=min_confidence, limit=safe_limit,
        )
        return {"ok": True, "results": results, "count": len(results)}

    # ── Schedules (Phase 9) ───────────────────────────────────────────────

    @app.get("/api/v1/schedules")
    def list_schedules_endpoint(
        deployment_id: str | None = None,
        enabled_only: bool = False,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        scope_filter = deployment_id
        if auth.scope != "admin":
            scope_filter = auth.deployment_id
        schedules = db.list_schedules(enabled_only=enabled_only, deployment_id=scope_filter)
        return {"ok": True, "schedules": schedules, "count": len(schedules)}

    @app.get("/api/v1/schedules/{schedule_id}")
    def get_schedule_endpoint(
        schedule_id: str, auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        schedule = db.get_schedule(schedule_id)
        if schedule is None:
            raise HTTPException(status_code=404, detail=f"unknown schedule: {schedule_id}")
        if auth.scope != "admin" and schedule["deployment_id"] != auth.deployment_id:
            raise HTTPException(status_code=403, detail="cross-deployment access denied")
        return {"ok": True, "schedule": schedule}

    @app.post("/api/v1/schedules")
    def create_schedule_endpoint(
        payload: Payload, auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        import uuid as _uuid_mod
        data = payload.data
        if not data.get("name"):
            raise HTTPException(status_code=400, detail="name is required")
        action_type = data.get("action_type")
        if not is_valid_action(action_type):
            raise HTTPException(
                status_code=400,
                detail=f"action_type must be one of {list(ACTION_TYPES)}",
            )
        # Validate cron expr early if provided
        cron_expr = data.get("cron_expr")
        if cron_expr:
            try:
                from croniter import croniter  # type: ignore
                if not croniter.is_valid(cron_expr):
                    raise ValueError(f"invalid cron expression: {cron_expr}")
            except ImportError:
                pass
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        schedule_id = data.get("schedule_id") or f"sched-{_uuid_mod.uuid4().hex[:12]}"
        deployment_id = _resolve_target_deployment(auth, data.get("deployment_id"))
        schedule = {
            "schedule_id": schedule_id,
            "deployment_id": deployment_id,
            "name": data["name"],
            "cron_expr": cron_expr,
            "starts_at": data.get("starts_at"),
            "ends_at": data.get("ends_at"),
            "action_type": action_type,
            "action_payload": data.get("action_payload", {}),
            "enabled": bool(data.get("enabled", True)),
        }
        db.add_schedule(schedule)
        return {"ok": True, "schedule": db.get_schedule(schedule_id)}

    @app.patch("/api/v1/schedules/{schedule_id}")
    def update_schedule_endpoint(
        schedule_id: str, payload: Payload,
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        existing = db.get_schedule(schedule_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"unknown schedule: {schedule_id}")
        _check_resource_deployment(auth, existing.get("deployment_id"))
        ok = db.update_schedule(schedule_id, payload.data)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown schedule: {schedule_id}")
        return {"ok": True, "schedule": db.get_schedule(schedule_id)}

    @app.delete("/api/v1/schedules/{schedule_id}")
    def delete_schedule_endpoint(
        schedule_id: str, auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        existing = db.get_schedule(schedule_id)
        if existing is not None:
            _check_resource_deployment(auth, existing.get("deployment_id"))
        ok = db.delete_schedule(schedule_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown schedule: {schedule_id}")
        return {"ok": True, "schedule_id": schedule_id, "deleted": True}

    @app.post("/api/v1/schedules/{schedule_id}/run")
    def run_schedule_now_endpoint(
        schedule_id: str, auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        existing = db.get_schedule(schedule_id)
        if existing is not None:
            _check_resource_deployment(auth, existing.get("deployment_id"))
        result = schedule_engine.run_now(schedule_id)
        return {
            "ok": result.status == "success",
            "schedule_id": result.schedule_id,
            "status": result.status,
            "detail": result.detail,
            "error": result.error,
        }

    @app.get("/api/v1/schedule-runs")
    def list_schedule_runs_endpoint(
        schedule_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 500))
        runs = db.list_schedule_runs(schedule_id=schedule_id, status=status, limit=safe_limit)
        return {"ok": True, "runs": runs, "count": len(runs)}

    # ── Profiles + states (Phase 8) ───────────────────────────────────────

    @app.get("/api/v1/profiles")
    def list_profiles_endpoint() -> dict[str, Any]:
        """Catalog of available device profiles with their behavioral defaults."""
        from clawcam_gateway.profiles import PROFILES, get_profile_defaults
        return {
            "ok": True,
            "profiles": [get_profile_defaults(p).to_dict() for p in PROFILES],
            "count": len(PROFILES),
        }

    @app.get("/api/v1/profiles/{profile_name}")
    def get_profile_endpoint(profile_name: str) -> dict[str, Any]:
        from clawcam_gateway.profiles import is_valid_profile, get_profile_defaults
        if not is_valid_profile(profile_name):
            raise HTTPException(status_code=404, detail=f"unknown profile: {profile_name}")
        return {"ok": True, "profile": get_profile_defaults(profile_name).to_dict()}

    @app.get("/api/v1/devices/{device_id}/state")
    def get_device_state_endpoint(device_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        _check_device_access(db, auth, device_id)
        row = db.get_device_profile_state(device_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        deployment_state = db.get_deployment_state(row.get("deployment_id") or "default")
        effective = row.get("state") or deployment_state or "normal"
        return {
            "ok": True,
            "device_id": device_id,
            "profile": row.get("profile"),
            "state": row.get("state"),
            "deployment_id": row.get("deployment_id"),
            "deployment_state": deployment_state,
            "effective_state": effective,
        }

    @app.patch("/api/v1/devices/{device_id}/state")
    def set_device_state_endpoint(
        device_id: str, payload: Payload,
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        from clawcam_gateway.profiles import is_valid_state
        new_state = str(payload.data.get("state") or "")
        if not is_valid_state(new_state):
            raise HTTPException(
                status_code=400,
                detail="invalid state; must be one of: normal, armed, disarmed, away, vacation, feeding, maintenance",
            )
        ok, prev = db.set_device_state(
            device_id, new_state,
            transitioned_by=auth.key_id or auth.key_name,
            reason=payload.data.get("reason"),
        )
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        return {"ok": True, "device_id": device_id, "previous_state": prev, "state": new_state}

    @app.patch("/api/v1/devices/{device_id}/profile")
    def set_device_profile_endpoint(
        device_id: str, payload: Payload,
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        from clawcam_gateway.profiles import is_valid_profile
        new_profile = str(payload.data.get("profile") or "")
        if not is_valid_profile(new_profile):
            raise HTTPException(status_code=400, detail=f"invalid profile: {new_profile}")
        ok = db.set_device_profile(device_id, new_profile)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        return {"ok": True, "device_id": device_id, "profile": new_profile}

    @app.patch("/api/v1/deployments/{deployment_id}/state")
    def set_deployment_state_endpoint(
        deployment_id: str, payload: Payload,
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        from clawcam_gateway.profiles import is_valid_state
        new_state = str(payload.data.get("state") or "")
        if not is_valid_state(new_state):
            raise HTTPException(status_code=400, detail="invalid state")
        ok, prev = db.set_deployment_state(
            deployment_id, new_state,
            transitioned_by=auth.key_id or auth.key_name,
            reason=payload.data.get("reason"),
        )
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown deployment: {deployment_id}")
        return {"ok": True, "deployment_id": deployment_id, "previous_state": prev, "state": new_state}

    @app.get("/api/v1/state-transitions")
    def list_state_transitions_endpoint(
        target_kind: str | None = None,
        target_id: str | None = None,
        deployment_id: str | None = None,
        limit: int = 50,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 500))
        scope_filter = deployment_id
        if auth.scope != "admin":
            scope_filter = auth.deployment_id
        transitions = db.list_state_transitions(
            target_kind=target_kind,
            target_id=target_id,
            deployment_id=scope_filter,
            limit=safe_limit,
        )
        return {"ok": True, "transitions": transitions, "count": len(transitions)}

    @app.post("/api/v1/devices")
    def register_device(payload: Payload, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
        try:
            validate_device(payload.data)
            db.upsert_device(payload.data)
        except Exception as exc:  # noqa: BLE001 - API returns validation details
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "device_id": payload.data["device_id"]}

    @app.get("/api/v1/devices")
    def list_devices(auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        devices = db.list_devices(deployment_id=_deployment_scope(auth))
        return {"devices": devices, "count": len(devices)}

    @app.post("/api/v1/events")
    def ingest_event(payload: Payload, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
        try:
            validate_event(payload.data)
            if db.get_device(payload.data["device_id"]) is None:
                raise ValueError(f"unknown device_id: {payload.data['device_id']}")
            db.add_event(payload.data)
        except Exception as exc:  # noqa: BLE001 - API returns validation details
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "event_id": payload.data["event_id"]}

    @app.post("/api/v1/health")
    def ingest_health(payload: Payload, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
        try:
            validate_health(payload.data)
            if db.get_device(payload.data["device_id"]) is None:
                raise ValueError(f"unknown device_id: {payload.data['device_id']}")
            db.add_health(payload.data)
        except Exception as exc:  # noqa: BLE001 - API returns validation details
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "device_id": payload.data["device_id"]}

    @app.get("/api/v1/detections/recent")
    def recent_detections(limit: int = 25, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        limit = max(1, min(limit, 100))
        return {"detections": db.recent_events(limit=limit, deployment_id=_deployment_scope(auth)), "limit": limit}

    @app.get("/api/v1/devices/{device_id}/health")
    def device_health(device_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        _check_device_access(db, auth, device_id)
        health = db.latest_health(device_id)
        if health is None:
            raise HTTPException(status_code=404, detail="no health record found")
        return health

    # ── Node command transport (Phase 2) ──────────────────────────────────

    @app.get("/api/v1/commands/{device_id}/pending")
    def get_pending_commands(
        device_id: str, limit: int = 10,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Return queued commands for a node. Called by the node on each wake cycle."""
        _check_device_access(db, auth, device_id)
        if db.get_device(device_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown device: {device_id}")
        safe_limit = max(1, min(limit, 50))
        # Atomic claim: fetch + mark delivered in one UPDATE...RETURNING so two
        # concurrent polls can never double-deliver, and the returned payloads
        # carry status='delivered' rather than a stale 'queued'.
        commands = db.claim_pending_commands(device_id, limit=safe_limit)
        return {"ok": True, "device_id": device_id, "commands": commands, "count": len(commands)}

    @app.post("/api/v1/commands/{command_id}/ack")
    def ack_command(command_id: str, ack: CommandAck, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
        """Node reports execution result for a delivered command."""
        allowed = {"executed", "failed", "skipped"}
        if ack.status not in allowed:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")
        updated = db.update_command_status(command_id, ack.status, result=ack.result)
        if not updated:
            raise HTTPException(status_code=404, detail=f"unknown command_id: {command_id}")
        return {"ok": True, "command_id": command_id, "status": ack.status}

    @app.get("/api/v1/devices/{device_id}/capabilities")
    def device_capabilities(device_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        _check_device_access(db, auth, device_id)
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
        auth: AuthContext = Depends(require_write),
    ) -> dict[str, Any]:
        """Accept a JPEG/PNG image from a node and trigger inference in the background.

        The event must already exist (registered via POST /api/v1/events).
        Inference runs asynchronously so this endpoint returns immediately.
        """
        # Traversal check first (400), then existence (404) — the id is used
        # as a path component below.
        if not _safe_path_component(event_id):
            raise HTTPException(status_code=400, detail="invalid event_id")
        event_row = db.get_event(event_id)
        if event_row is None:
            raise HTTPException(status_code=404, detail=f"unknown event: {event_id}")

        _existing = db.get_inference_result(event_id)
        if _existing is not None and _existing.get("model_name") != "mock_detector":
            # Already processed; accept the upload but skip re-inference
            return {"ok": True, "event_id": event_id, "inference": "already_processed"}
        # Save the uploaded file into the configured media directory
        config.media_dir.mkdir(parents=True, exist_ok=True)
        suffix = _safe_suffix(file.filename, (".jpg", ".jpeg", ".png"), ".jpg")
        content = await file.read()
        if len(content) > MAX_MEDIA_BYTES:
            raise HTTPException(status_code=413, detail="media upload exceeds size limit")
        dest = (config.media_dir / f"{event_id}{suffix}").resolve()
        if not dest.is_relative_to(config.media_dir.resolve()):
            raise HTTPException(status_code=400, detail="invalid media path")
        dest.write_bytes(content)

        # Phase 10: apply privacy masks if any zones with action='privacy_mask'
        # exist for the originating device. Done synchronously before
        # inference because the masked frame is what gets analysed and stored.
        try:
            originating_device = event_row.get("device_id")
            if originating_device:
                zones = db.list_detection_zones(
                    device_id=originating_device, enabled_only=True,
                )
                if any(z.get("action") == "privacy_mask" for z in zones):
                    from clawcam_gateway.zones import apply_privacy_masks
                    apply_privacy_masks(dest, zones)
        except Exception as exc:  # noqa: BLE001 - never block ingest on mask errors
            # Loudly logged: a swallowed failure here means an UNMASKED frame
            # persists for a device whose zones promise privacy masking.
            import logging
            logging.getLogger(__name__).warning(
                "privacy mask application failed for event %s: %s", event_id, exc,
            )

        # Phase 12: orchestrator runs the full detector chain configured for
        # this device's profile (with per-device override if set). Legacy
        # single-detector pipeline kept as a fallback for tests that don't
        # set up a device row first.
        originating_device_id = event_row.get("device_id")
        if originating_device_id:
            background_tasks.add_task(
                inference_orchestrator.run, event_id, str(dest),
                originating_device_id,
            )
        else:
            background_tasks.add_task(pipeline.run, event_id, str(dest))
        # Evaluate alert rules after inference completes. The originating
        # device_id must be passed so device-scoped rules, required_state
        # gating, and detection-zone filtering all apply (they are skipped
        # when device_id is None).
        background_tasks.add_task(alert_evaluator.evaluate, event_id, originating_device_id)
        # Queue cloud upload alongside inference (noop when cloud is disabled)
        background_tasks.add_task(cloud_worker.queue_and_upload, dest, event_id)
        return {"ok": True, "event_id": event_id, "media_path": str(dest), "inference": "queued"}

    @app.get("/api/v1/events/{event_id}/inference")
    def get_event_inference(event_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        _check_event_access(db, auth, event_id)
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
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """List recent inference results with optional filters."""
        safe_limit = max(1, min(limit, 100))
        results = db.list_inference_results(
            limit=safe_limit,
            label=label,
            min_confidence=min_confidence,
            species=species,
            deployment_id=_deployment_scope(auth),
        )
        return {"ok": True, "results": results, "count": len(results)}

    # ── Cloud sync (Phase 4) ─────────────────────────────────────────────

    @app.get("/api/v1/cloud/uploads")
    def cloud_upload_status(
        limit: int = 25,
        status: str | None = None,
        auth: AuthContext = Depends(get_auth_context),
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
    def create_alert_rule(payload: Payload, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
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
            "severity": (data.get("severity") or "warning"),
        }
        db.add_alert_rule(rule)
        return {"ok": True, "rule": rule}

    @app.get("/api/v1/alert-rules")
    def list_alert_rules_endpoint(
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Return all configured alert rules (webhook URLs may embed secrets)."""
        rules = db.list_alert_rules()
        return {"ok": True, "rules": rules, "count": len(rules)}

    @app.get("/api/v1/alert-rules/{rule_id}")
    def get_alert_rule(
        rule_id: str, auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Return a single alert rule by ID."""
        rule = db.get_alert_rule(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail=f"unknown rule_id: {rule_id}")
        return {"ok": True, "rule": rule}

    @app.patch("/api/v1/alert-rules/{rule_id}")
    def update_alert_rule(rule_id: str, payload: Payload, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
        """Partially update an alert rule (enabled/disabled, webhook_url, etc.)."""
        updated = db.update_alert_rule(rule_id, payload.data)
        if not updated:
            raise HTTPException(status_code=404, detail=f"unknown rule_id: {rule_id}")
        return {"ok": True, "rule_id": rule_id, "updated": list(payload.data.keys())}

    @app.delete("/api/v1/alert-rules/{rule_id}")
    def delete_alert_rule(rule_id: str, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
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
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Return recent fired alert events."""
        safe_limit = max(1, min(limit, 200))
        events = db.list_alert_events(
            limit=safe_limit,
            rule_id=rule_id,
            delivery_status=delivery_status,
            deployment_id=_deployment_scope(auth),
        )
        return {"ok": True, "alerts": events, "count": len(events)}

    @app.get("/api/v1/alerts/digest")
    def alert_digest_endpoint(
        window_s: int = 86400,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Roll up alert events over a trailing window (default 24h) by rule and species."""
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        from clawcam_gateway.alerts.digest import build_alert_digest

        window_s = max(1, int(window_s))
        since = (_dt.now(_tz.utc) - _td(seconds=window_s)).isoformat()
        events = db.list_alert_events(
            limit=100_000, since=since, deployment_id=_deployment_scope(auth),
        )
        return {"ok": True, "digest": build_alert_digest(events, window_label=f"{window_s}s")}

    @app.get("/api/v1/analytics/activity")
    def activity_report_endpoint(
        limit: int = 5000,
        species: str | None = None,
        min_confidence: float = 0.0,
        tz_offset_hours: int = 0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Per-subject hour-of-day activity + diel pattern over recent detections."""
        from clawcam_gateway.analytics.activity import build_activity_report

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(
            limit=safe_limit,
            species=species,
            min_confidence=min_confidence,
            deployment_id=_deployment_scope(auth),
        )
        return {
            "ok": True,
            "report": build_activity_report(dets, tz_offset_hours=int(tz_offset_hours)),
        }

    @app.get("/api/v1/analytics/trends")
    def trend_report_endpoint(
        limit: int = 5000,
        species: str | None = None,
        min_confidence: float = 0.0,
        tz_offset_hours: int = 0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Day-over-day detection trends per subject (rising / falling / steady)."""
        from clawcam_gateway.analytics.trends import build_trend_report

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(
            limit=safe_limit,
            species=species,
            min_confidence=min_confidence,
            deployment_id=_deployment_scope(auth),
        )
        return {
            "ok": True,
            "report": build_trend_report(dets, tz_offset_hours=int(tz_offset_hours)),
        }

    @app.get("/api/v1/analytics/site")
    def site_report_endpoint(
        limit: int = 5000,
        min_confidence: float = 0.0,
        tz_offset_hours: int = 0,
        digest_window_s: int = 604800,  # 7 days
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Combined site summary — activity + trends + alert digest in one report."""
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        from clawcam_gateway.analytics.site import build_site_report

        safe_limit = max(1, min(int(limit), 50_000))
        scope = _deployment_scope(auth)
        dets = db.list_inference_results(
            limit=safe_limit, min_confidence=min_confidence, deployment_id=scope,
        )
        window = max(1, int(digest_window_s))
        since = (_dt.now(_tz.utc) - _td(seconds=window)).isoformat()
        alerts = db.list_alert_events(limit=50_000, since=since, deployment_id=scope)
        return {
            "ok": True,
            "report": build_site_report(
                dets, alerts, tz_offset_hours=int(tz_offset_hours),
                digest_window_label=f"{window}s",
            ),
        }

    @app.get("/api/v1/analytics/diversity")
    def diversity_report_endpoint(
        limit: int = 5000,
        min_confidence: float = 0.0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Species diversity metrics — richness, Shannon index, evenness, dominance."""
        from clawcam_gateway.analytics.diversity import build_diversity_report

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(
            limit=safe_limit, min_confidence=min_confidence, deployment_id=_deployment_scope(auth),
        )
        return {"ok": True, "report": build_diversity_report(dets)}

    @app.get("/api/v1/analytics/comparison")
    def comparison_report_endpoint(
        window_days: int = 7,
        limit: int = 10000,
        min_confidence: float = 0.0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Period-over-period comparison — last window_days vs the window before it."""
        from datetime import datetime, timedelta, timezone

        from clawcam_gateway.analytics.compare import build_comparison_report

        safe_limit = max(1, min(int(limit), 50_000))
        days = max(1, int(window_days))
        now = datetime.now(timezone.utc)
        cur_start = (now - timedelta(days=days)).isoformat()
        prev_start = (now - timedelta(days=2 * days)).isoformat()
        rows = db.list_inference_results(
            limit=safe_limit, min_confidence=min_confidence, deployment_id=_deployment_scope(auth),
        )
        current = [r for r in rows if str(r.get("ran_at", "")) >= cur_start]
        previous = [r for r in rows if prev_start <= str(r.get("ran_at", "")) < cur_start]
        return {
            "ok": True,
            "report": build_comparison_report(
                current, previous,
                current_label=f"last {days}d", previous_label=f"prior {days}d",
            ),
        }

    @app.get("/api/v1/analytics/encounters")
    def encounter_report_endpoint(
        gap_minutes: int = 30,
        limit: int = 5000,
        min_confidence: float = 0.0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Independent-encounter counts — lingering captures collapsed into visits."""
        from clawcam_gateway.analytics.encounters import build_encounter_report

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(
            limit=safe_limit, min_confidence=min_confidence, deployment_id=_deployment_scope(auth),
        )
        return {"ok": True, "report": build_encounter_report(dets, gap_minutes=int(gap_minutes))}

    @app.get("/api/v1/analytics/calibration")
    def calibration_report_endpoint(
        limit: int = 5000,
        buckets: int = 10,
        target_precision: float = 0.9,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Confidence calibration from human review + recommended accept threshold."""
        from clawcam_gateway.analytics.calibration import build_calibration_report

        safe_limit = max(1, min(int(limit), 50_000))
        rows = db.list_inference_results(limit=safe_limit, deployment_id=_deployment_scope(auth))
        return {
            "ok": True,
            "report": build_calibration_report(
                rows, buckets=int(buckets), target_precision=float(target_precision),
            ),
        }

    @app.get("/api/v1/analytics/anomalies")
    def anomaly_report_endpoint(
        limit: int = 5000,
        z_threshold: float = 2.0,
        tz_offset_hours: int = 0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Daily detection-count anomalies — spikes and drops vs the site baseline."""
        from clawcam_gateway.analytics.anomaly import build_anomaly_report

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(limit=safe_limit, deployment_id=_deployment_scope(auth))
        return {
            "ok": True,
            "report": build_anomaly_report(
                dets, z_threshold=float(z_threshold), tz_offset_hours=int(tz_offset_hours),
            ),
        }

    @app.get("/api/v1/analytics/cooccurrence")
    def cooccurrence_report_endpoint(
        limit: int = 5000,
        window_minutes: int = 60,
        tz_offset_hours: int = 0,
        min_shared: int = 1,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Species co-occurrence — window Jaccard + activity overlap per species pair."""
        from clawcam_gateway.analytics.cooccurrence import build_cooccurrence_report

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(limit=safe_limit, deployment_id=_deployment_scope(auth))
        return {
            "ok": True,
            "report": build_cooccurrence_report(
                dets, window_minutes=int(window_minutes),
                tz_offset_hours=int(tz_offset_hours), min_shared=int(min_shared),
            ),
        }

    @app.get("/api/v1/analytics/abundance")
    def abundance_report_endpoint(
        limit: int = 5000,
        tz_offset_hours: int = 0,
        trap_days: int | None = None,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Relative abundance index — detections per 100 trap-days per species."""
        from clawcam_gateway.analytics.abundance import build_abundance_report

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(limit=safe_limit, deployment_id=_deployment_scope(auth))
        return {
            "ok": True,
            "report": build_abundance_report(
                dets, tz_offset_hours=int(tz_offset_hours),
                trap_days=None if trap_days is None else int(trap_days),
            ),
        }

    @app.get("/api/v1/analytics/species")
    def species_profile_endpoint(
        subject: str,
        limit: int = 5000,
        tz_offset_hours: int = 0,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Single-species drill-down: abundance, diel, trend, encounters, co-occurring."""
        from clawcam_gateway.analytics.species import build_species_profile

        safe_limit = max(1, min(int(limit), 50_000))
        dets = db.list_inference_results(limit=safe_limit, deployment_id=_deployment_scope(auth))
        return {"ok": True, "report": build_species_profile(
            dets, subject, tz_offset_hours=int(tz_offset_hours))}

    # ── Data export (Phase 5) ────────────────────────────────────────────

    @app.get("/api/v1/export/events.csv")
    def export_events(
        limit: int = 1000,
        device_id: str | None = None,
        auth: AuthContext = Depends(get_auth_context),
    ) -> StreamingResponse:
        """Download recent events as a CSV file."""
        safe_limit = max(1, min(limit, 10000))
        csv_text = export_events_csv(db, limit=safe_limit, device_id=device_id,
                                     deployment_id=_deployment_scope(auth))
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
        auth: AuthContext = Depends(get_auth_context),
    ) -> StreamingResponse:
        """Download recent inference detections as a CSV file."""
        safe_limit = max(1, min(limit, 10000))
        csv_text = export_detections_csv(
            db,
            limit=safe_limit,
            label=label,
            min_confidence=min_confidence,
            species=species,
            deployment_id=_deployment_scope(auth),
        )
        filename = csv_filename("detections")
        return StreamingResponse(
            iter([csv_text]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Cloud retry (Phase 5) ────────────────────────────────────────────

    @app.post("/api/v1/cloud/retry")
    def retry_failed_uploads(background_tasks: BackgroundTasks, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
        """Retry all failed cloud uploads in the background.

        Each retry transitions the EXISTING cloud_uploads row (previously a
        new row was inserted per attempt, so the failed counter only grew).
        """
        failed = db.list_cloud_uploads(status="failed", limit=500)
        for upload in failed:
            background_tasks.add_task(cloud_worker.retry_upload, upload)
        return {
            "ok": True,
            "retried": len(failed),
            "message": f"{len(failed)} failed upload(s) re-queued for retry.",
        }

    # ── Firmware OTA (Phase 3C) ───────────────────────────────────────────

    @app.post("/api/v1/firmware")
    async def upload_firmware(file: UploadFile, auth: AuthContext = Depends(require_write)) -> dict[str, Any]:
        """Upload a firmware .bin image. Returns build_id, sha256, and download URL.

        The node uses the download URL in the firmware_update command payload.
        Firmware binaries are served back at GET /api/v1/firmware/{build_id}/download.
        """
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="empty firmware file")
        if len(content) > MAX_FIRMWARE_BYTES:
            raise HTTPException(status_code=413, detail="firmware upload exceeds size limit")

        sha256 = hashlib.sha256(content).hexdigest()
        build_id = _uuid.uuid4().hex[:16]
        # Use only the basename and strip anything outside a safe charset (no traversal).
        base_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename or "firmware.bin").name) or "firmware.bin"
        safe_name = f"{build_id}_{base_name}"

        fw_dir = config.media_dir / "firmware"
        fw_dir.mkdir(parents=True, exist_ok=True)
        dest = (fw_dir / safe_name).resolve()
        if not dest.is_relative_to(fw_dir.resolve()):
            raise HTTPException(status_code=400, detail="invalid firmware path")
        dest.write_bytes(content)

        # Extract version from filename if present (e.g. "clawcam-node-0.2.0.bin")
        stem = Path(base_name).stem
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
    def list_firmware(auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        """List all uploaded firmware builds."""
        builds = db.list_firmware_builds()
        return {"ok": True, "builds": builds, "count": len(builds)}

    @app.get("/api/v1/firmware/{build_id}")
    def get_firmware_build(
        build_id: str, auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Return metadata for a specific firmware build."""
        build = db.get_firmware_build(build_id)
        if build is None:
            raise HTTPException(status_code=404, detail=f"unknown build_id: {build_id}")
        return {"ok": True, "build": build}

    @app.get("/api/v1/firmware/{build_id}/download")
    def download_firmware(
        build_id: str, auth: AuthContext = Depends(get_auth_context),
    ) -> FileResponse:
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
        # Single source of truth: derive the full catalog from the MCP tool
        # definitions + approval set, so this endpoint can never drift from what
        # the MCP server advertises and the brain actually sees.
        from clawcam_gateway.mcp_server.stdio_server import tool_catalog

        return {"tools": tool_catalog()}

    @app.post("/api/v1/tools/{tool_name}")
    def call_tool(
        tool_name: str, request: ToolRequest,
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        # Mutating (approval-gated) tools require write scope; reads require
        # any authenticated context. Without this, an anonymous caller could
        # invoke capture_now / apply_config_patch / queue_firmware_update etc.
        from clawcam_gateway.mcp_server.stdio_server import APPROVAL_REQUIRED_TOOLS
        if tool_name in APPROVAL_REQUIRED_TOOLS:
            try:
                auth.require(SCOPE_WRITE)
            except ScopeRequired as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        result = dispatch_tool(
            tool_name, request.arguments,
            database_path=config.database_path,
            mqtt_bridge=bridge,
            source="rest",
        )
        if not result.get("ok", False) and result.get("error", "").startswith("unknown"):
            raise HTTPException(status_code=404, detail=result)
        return result

    # ── Observability (Phase 13 WS5) ─────────────────────────────────────

    @app.get("/api/v1/metrics")
    def metrics(auth: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
        """Gateway counters + per-tool call statistics from the audit table."""

        tool_stats = db.tool_call_stats()
        return {
            "ok": True,
            "counts": {
                "devices": len(db.list_devices()),
                "events": len(db.recent_events(limit=10_000)),
                "inference_results": len(db.list_inference_results(limit=10_000)),
                "alerts_fired": len(db.list_alert_events(limit=10_000)),
            },
            "tool_calls": {
                "total": sum(s["calls"] for s in tool_stats),
                "errors": sum(s["errors"] or 0 for s in tool_stats),
                "by_tool": tool_stats,
            },
        }

    @app.get("/api/v1/tool-audit")
    def tool_audit(
        limit: int = 100, auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Most recent tool-call audit rows (caller, args hash, latency)."""

        return {"ok": True, "audit": db.list_tool_call_audit(limit=limit)}

    @app.get("/api/v1/dashboard")
    def dashboard_data(
        limit: int = 25, auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        return _dashboard_payload(db, config, limit)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(
        limit: int = 25, auth: AuthContext = Depends(get_auth_context),
    ) -> HTMLResponse:
        return HTMLResponse(render_dashboard(_dashboard_payload(db, config, limit)))

    @app.get("/ops", response_class=HTMLResponse)
    def ops_dashboard() -> HTMLResponse:
        """Live, self-refreshing ops dashboard (polls the JSON API, same-origin)."""
        return HTMLResponse(render_ops_dashboard())

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


def app_factory() -> FastAPI:
    """Uvicorn factory entrypoint: ``uvicorn --factory clawcam_gateway.api.app:app_factory``.

    A module-level ``app = create_app()`` used to run here, which meant
    merely importing this module created and migrated a SQLite database in
    the current working directory (the source of stray ``clawcam_gateway.db``
    files at repo root). Construct the app explicitly instead.
    """
    return create_app()
