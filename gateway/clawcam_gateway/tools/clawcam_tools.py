"""MCP-style gateway tools for ClawCam brain integrations.

These functions are intentionally plain Python callables so they can be wrapped by an
MCP server, an HTTP endpoint, or an Oh-Ben-Claw tool adapter without duplicating
business logic.

Approval policy:
  - get_recent_detections, get_node_health, generate_daily_summary, list_pending_commands:
    read-only, no approval required.
  - capture_now, apply_config_patch:
    approval-gated. The brain enforces human approval before calling these.
    The gateway queues them as pending commands that field nodes can poll.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from clawcam_gateway.ingest.export import export_detections_csv as _export_detections_csv
from clawcam_gateway.storage.database import GatewayDatabase


@dataclass
class ToolContext:
    """Shared context for ClawCam gateway tool calls."""

    database_path: Path | str = "clawcam_gateway.db"
    mqtt_bridge: Optional[Any] = field(default=None, repr=False)  # MQTTBridge | None

    @property
    def db(self) -> GatewayDatabase:
        return GatewayDatabase(self.database_path)

    def publish_command(self, device_id: str, command: dict[str, Any]) -> bool:
        """Push a queued command to the node via MQTT if bridge is active."""
        if self.mqtt_bridge is not None:
            return self.mqtt_bridge.publish_command(device_id, command)
        return False


def get_recent_detections(context: ToolContext, limit: int = 25) -> dict[str, Any]:
    """Return recent detection/event records from the gateway database."""

    safe_limit = max(1, min(int(limit), 100))
    detections = context.db.recent_events(limit=safe_limit)
    return {"ok": True, "limit": safe_limit, "detections": detections}


def get_node_health(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the latest health payload for a device."""

    health = context.db.latest_health(device_id)
    if health is None:
        return {"ok": False, "error": f"no health record found for {device_id}", "device_id": device_id}
    return {"ok": True, "device_id": device_id, "health": health}


def generate_daily_summary(
    context: ToolContext,
    report_date: str | None = None,
    deployment_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Generate a structured summary from recent gateway events."""

    events = context.db.recent_events(limit=max(1, min(int(limit), 500)))
    if report_date:
        events = [event for event in events if event.get("timestamp", "").startswith(report_date)]
    else:
        report_date = date.today().isoformat()
    if deployment_id:
        events = [event for event in events if event.get("deployment_id") == deployment_id]

    event_counts = Counter(event.get("event_type", "unknown") for event in events)
    label_counts: Counter[str] = Counter()
    for event in events:
        for classification in event.get("classifications", []):
            label_counts[classification.get("label", "unknown")] += 1

    return {
        "ok": True,
        "date": report_date,
        "deployment_id": deployment_id,
        "event_count": len(events),
        "event_counts": dict(event_counts),
        "label_counts": dict(label_counts),
        "summary": _summary_sentence(len(events), event_counts, label_counts),
    }


def list_capabilities(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the ESP-Claw capability groups declared by a node."""

    device = context.db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}
    caps = device.get("capabilities", [])
    return {
        "ok": True,
        "device_id": device_id,
        "capabilities": caps,
        "has_camera_trap": "cap_clawcam_camera_trap" in caps,
        "has_power": "cap_clawcam_power" in caps,
        "has_storage": "cap_clawcam_storage" in caps,
        "has_sensors": "cap_clawcam_sensors" in caps,
        "has_events": "cap_clawcam_events" in caps,
        "has_firmware_ota": "cap_clawcam_firmware_ota" in caps,
    }


def capture_now(context: ToolContext, device_id: str, reason: str | None = None) -> dict[str, Any]:
    """Queue a manual capture command for a ClawCam node.

    The node polls GET /api/v1/commands/{device_id}/pending on each wake cycle
    and executes queued commands. Requires cap_clawcam_camera_trap capability.
    The brain enforces human approval before calling this tool.
    """

    db = context.db
    device = db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}

    caps = device.get("capabilities", [])
    if caps and "cap_clawcam_camera_trap" not in caps:
        return {
            "ok": False,
            "error": f"device {device_id} does not declare cap_clawcam_camera_trap",
            "device_id": device_id,
            "capabilities": caps,
        }

    command_id = f"cmd-capture-{uuid.uuid4().hex[:12]}"
    command = {
        "command_id": command_id,
        "command_type": "capture_now",
        "device_id": device_id,
        "status": "queued",
        "reason": reason or "manual capture requested via brain",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add_pending_command(command)
    mqtt_pushed = context.publish_command(device_id, command)

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "status": "queued",
        "mqtt_pushed": mqtt_pushed,
        "message": "Capture command queued. The node will execute it on its next wake cycle.",
    }


def apply_config_patch(
    context: ToolContext,
    device_id: str,
    patch: dict[str, Any],
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Queue an approved configuration patch for a ClawCam node or gateway.

    The patch is validated and stored as a pending command. The brain enforces
    human approval before calling this tool; approval_id is recorded for audit.
    """

    if not isinstance(patch, dict) or not patch:
        return {
            "ok": False,
            "error": "patch must be a non-empty object",
            "device_id": device_id,
        }

    db = context.db
    device = db.get_device(device_id)
    if device is None:
        return {
            "ok": False,
            "error": f"unknown device: {device_id}",
            "device_id": device_id,
        }

    _validate_config_patch(patch)

    command_id = f"cmd-config-{uuid.uuid4().hex[:12]}"
    command = {
        "command_id": command_id,
        "command_type": "apply_config_patch",
        "device_id": device_id,
        "status": "queued",
        "patch": patch,
        "approval_id": approval_id,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add_pending_command(command)
    mqtt_pushed = context.publish_command(device_id, command)

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "status": "queued",
        "patch_keys": list(patch.keys()),
        "approval_id": approval_id,
        "mqtt_pushed": mqtt_pushed,
        "message": "Config patch queued. The node will apply it on its next wake cycle.",
    }


def list_pending_commands(
    context: ToolContext,
    device_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Return pending commands queued for field nodes."""

    commands = context.db.list_pending_commands(device_id=device_id, status=status)
    return {
        "ok": True,
        "device_id": device_id,
        "status_filter": status,
        "count": len(commands),
        "commands": commands,
    }


def list_firmware_builds(context: ToolContext) -> dict[str, Any]:
    """List all firmware builds uploaded to the gateway."""
    builds = context.db.list_firmware_builds()
    return {"ok": True, "count": len(builds), "builds": builds}


def queue_firmware_update(
    context: ToolContext,
    device_id: str,
    build_id: str,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Queue an OTA firmware update command for a ClawCam node.

    Requires cap_clawcam_firmware_ota capability. The gateway serves the binary
    at a stable download URL embedded in the command payload. The node verifies
    SHA256 before flashing. Approval-gated.
    """
    db = context.db
    device = db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}

    caps = device.get("capabilities", [])
    if caps and "cap_clawcam_firmware_ota" not in caps:
        return {
            "ok": False,
            "error": f"device {device_id} does not declare cap_clawcam_firmware_ota",
            "device_id": device_id,
            "capabilities": caps,
        }

    build = db.get_firmware_build(build_id)
    if build is None:
        return {"ok": False, "error": f"unknown build_id: {build_id}", "build_id": build_id}

    command_id = f"cmd-ota-{uuid.uuid4().hex[:12]}"
    command = {
        "command_id": command_id,
        "command_type": "firmware_update",
        "device_id": device_id,
        "status": "queued",
        "build_id": build_id,
        "version": build["version"],
        "firmware_url": f"/api/v1/firmware/{build_id}/download",
        "sha256": build["sha256"],
        "size_bytes": build["size_bytes"],
        "approval_id": approval_id,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add_pending_command(command)
    mqtt_pushed = context.publish_command(device_id, command)

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "build_id": build_id,
        "version": build["version"],
        "sha256": build["sha256"],
        "status": "queued",
        "mqtt_pushed": mqtt_pushed,
        "message": f"Firmware update to {build['version']} queued. Node will apply on next wake cycle.",
    }


def get_inference_results(context: ToolContext, event_id: str) -> dict[str, Any]:
    """Return species detection results for a specific captured event.

    Inference runs automatically after a node uploads media via the gateway.
    Returns the top detection label, confidence, and full bounding-box list.
    """
    result = context.db.get_inference_result(event_id)
    if result is None:
        return {
            "ok": False,
            "error": f"no inference result found for event {event_id}",
            "event_id": event_id,
        }
    return {"ok": True, "event_id": event_id, "result": result}


def list_species_detections(
    context: ToolContext,
    limit: int = 25,
    label: str | None = None,
    min_confidence: float = 0.5,
    species: str | None = None,
) -> dict[str, Any]:
    """List recent inference results with optional species/label filtering.

    Useful for asking questions like:
      - "What animals have been detected in the last 24 hours?"
      - "Show me all deer detections with confidence above 0.8"
      - "How many person detections occurred this week?"

    Arguments
    ---------
    limit:          Maximum results to return (1–100, default 25).
    label:          Filter by detection label: "animal", "person", "vehicle".
    min_confidence: Minimum top_confidence score (default 0.5).
    species:        Substring match on species name (e.g. "deer").
    """
    safe_limit = max(1, min(int(limit), 100))
    results = context.db.list_inference_results(
        limit=safe_limit,
        label=label,
        min_confidence=float(min_confidence),
        species=species,
    )
    label_counts: Counter[str] = Counter(
        r["top_label"] for r in results if r["top_label"]
    )
    species_counts: Counter[str] = Counter(
        r["top_species"] for r in results if r["top_species"]
    )
    return {
        "ok": True,
        "count": len(results),
        "label_counts": dict(label_counts),
        "species_counts": dict(species_counts),
        "results": results,
    }


def get_cloud_sync_status(
    context: ToolContext,
    limit: int = 25,
    status: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Return cloud upload status for recent media files.

    Shows which images have been successfully synced to cloud storage,
    which are pending, and which failed (with error messages).

    Arguments
    ---------
    limit:    Maximum results to return (1–100, default 25).
    status:   Filter by upload status: "pending", "uploaded", or "failed".
    event_id: Filter to a specific event.
    """
    db = context.db
    safe_limit = max(1, min(int(limit), 100))
    uploads = db.list_cloud_uploads(
        limit=safe_limit,
        status=status,
        event_id=event_id,
    )
    summary = db.get_cloud_upload_summary()
    return {
        "ok": True,
        "summary": summary,
        "count": len(uploads),
        "uploads": uploads,
    }


def export_detections_csv(
    context: ToolContext,
    limit: int = 1000,
    label: str | None = None,
    min_confidence: float = 0.0,
    species: str | None = None,
) -> dict[str, Any]:
    """Export recent inference results as CSV text.

    Returns a CSV-formatted string embedding the detection records so a brain
    or downstream tool can write it to disk or display it inline.

    Arguments
    ---------
    limit:          Maximum rows to export (1–10000, default 1000).
    label:          Filter by detection label: "animal", "person", "vehicle".
    min_confidence: Minimum top_confidence score (default 0.0 = all results).
    species:        Substring match on species name (e.g. "deer").
    """
    safe_limit = max(1, min(int(limit), 10000))
    csv_text = _export_detections_csv(
        context.db,
        limit=safe_limit,
        label=label,
        min_confidence=float(min_confidence),
        species=species,
    )
    row_count = max(0, csv_text.count("\n") - 1)  # subtract header row
    return {
        "ok": True,
        "csv": csv_text,
        "row_count": row_count,
        "filters": {
            "limit": safe_limit,
            "label": label,
            "min_confidence": min_confidence,
            "species": species,
        },
    }


def list_alert_rules(context: ToolContext) -> dict[str, Any]:
    """Return all configured alert rules.

    Alert rules fire webhook notifications when the AI detects matching species,
    labels, or confidence levels. Read-only — creating rules requires approval.
    """
    rules = context.db.list_alert_rules()
    return {"ok": True, "count": len(rules), "rules": rules}


def list_recent_alerts(
    context: ToolContext,
    limit: int = 25,
    rule_id: str | None = None,
    delivery_status: str | None = None,
) -> dict[str, Any]:
    """Return recent fired alert events.

    Each entry shows which rule fired, what was detected, when, and whether
    the webhook delivery succeeded.

    Arguments
    ---------
    limit:           Maximum results to return (1–200, default 25).
    rule_id:         Filter to a specific rule.
    delivery_status: Filter by delivery status: "delivered" or "failed".
    """
    safe_limit = max(1, min(int(limit), 200))
    events = context.db.list_alert_events(
        limit=safe_limit,
        rule_id=rule_id,
        delivery_status=delivery_status,
    )
    return {"ok": True, "count": len(events), "alerts": events}


def create_alert_rule(
    context: ToolContext,
    name: str,
    webhook_url: str | None = None,
    label: str | None = None,
    min_confidence: float = 0.5,
    species_pattern: str | None = None,
    device_id: str | None = None,
) -> dict[str, Any]:
    """Create a new alert rule that fires a webhook on matching detections.

    The rule is stored persistently in the gateway database and evaluated after
    every inference result. Approval-gated — modifies gateway state.

    Arguments
    ---------
    name:            Human-readable name for the rule (required).
    webhook_url:     HTTP(S) endpoint to POST when the rule fires.
                     Falls back to CLAWCAM_ALERT_WEBHOOK_URL if not set.
    label:           Restrict to "animal", "person", or "vehicle". None = any.
    min_confidence:  Minimum top_confidence to fire (default 0.5).
    species_pattern: Case-insensitive substring match on species name.
    device_id:       Only fire for events from this specific device.
    """
    if not name or not name.strip():
        return {"ok": False, "error": "name is required"}

    allowed_labels = {"animal", "person", "vehicle", None}
    if label not in allowed_labels:
        return {
            "ok": False,
            "error": f"label must be one of: animal, person, vehicle (got {label!r})",
        }

    safe_confidence = max(0.0, min(float(min_confidence), 1.0))

    rule = {
        "rule_id": f"rule-{uuid.uuid4().hex[:12]}",
        "name": name.strip(),
        "label": label,
        "min_confidence": safe_confidence,
        "species_pattern": species_pattern,
        "device_id": device_id,
        "webhook_url": webhook_url,
        "enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    context.db.add_alert_rule(rule)
    return {
        "ok": True,
        "created": True,
        "rule": rule,
        "message": f"Alert rule '{name}' created. It will fire when detections match the criteria.",
    }


def list_profiles(context: ToolContext) -> dict[str, Any]:
    """List all available device profiles with their behavioral defaults."""
    from clawcam_gateway.profiles import PROFILES, get_profile_defaults
    return {
        "ok": True,
        "count": len(PROFILES),
        "profiles": [get_profile_defaults(p).to_dict() for p in PROFILES],
    }


def get_device_state(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the profile + state of a device, with deployment-level fallback."""
    row = context.db.get_device_profile_state(device_id)
    if row is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}
    deployment_id = row.get("deployment_id") or "default"
    deployment_state = context.db.get_deployment_state(deployment_id)
    effective = row.get("state") or deployment_state or "normal"
    return {
        "ok": True,
        "device_id": device_id,
        "profile": row.get("profile"),
        "state": row.get("state"),
        "deployment_id": deployment_id,
        "deployment_state": deployment_state,
        "effective_state": effective,
    }


def set_device_state(
    context: ToolContext,
    device_id: str,
    state: str,
    reason: str | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Change the runtime state of a device. Approval-gated (changes behavior).

    Allowed states: normal, armed, disarmed, away, vacation, feeding, maintenance.
    Every transition is recorded in the state_transitions audit table.
    """
    from clawcam_gateway.profiles import is_valid_state
    if not is_valid_state(state):
        return {
            "ok": False,
            "error": f"invalid state '{state}'; must be one of "
                     "normal, armed, disarmed, away, vacation, feeding, maintenance",
        }
    ok, prev = context.db.set_device_state(
        device_id, state,
        transitioned_by=approval_id or "mcp_tool",
        reason=reason,
    )
    if not ok:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}
    return {
        "ok": True,
        "device_id": device_id,
        "previous_state": prev,
        "state": state,
        "message": f"Device {device_id} transitioned {prev} → {state}.",
    }


def set_deployment_state(
    context: ToolContext,
    deployment_id: str,
    state: str,
    reason: str | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Change the runtime state of an entire deployment. Approval-gated.

    All devices in the deployment whose own state is unset inherit this value.
    Useful for "arm the whole house" or "switch the apiary to maintenance".
    """
    from clawcam_gateway.profiles import is_valid_state
    if not is_valid_state(state):
        return {"ok": False, "error": f"invalid state '{state}'"}
    ok, prev = context.db.set_deployment_state(
        deployment_id, state,
        transitioned_by=approval_id or "mcp_tool",
        reason=reason,
    )
    if not ok:
        return {"ok": False, "error": f"unknown deployment: {deployment_id}"}
    return {
        "ok": True,
        "deployment_id": deployment_id,
        "previous_state": prev,
        "state": state,
        "message": f"Deployment {deployment_id} transitioned {prev} → {state}.",
    }


def list_state_transitions(
    context: ToolContext,
    target_kind: str | None = None,
    target_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return recent state transitions for diagnostics and audit."""
    safe_limit = max(1, min(int(limit), 500))
    transitions = context.db.list_state_transitions(
        target_kind=target_kind,
        target_id=target_id,
        limit=safe_limit,
    )
    return {"ok": True, "count": len(transitions), "transitions": transitions}


def list_schedules(
    context: ToolContext,
    deployment_id: str | None = None,
    enabled_only: bool = False,
) -> dict[str, Any]:
    """List all schedules (optionally filtered to enabled and/or one deployment)."""
    schedules = context.db.list_schedules(enabled_only=enabled_only, deployment_id=deployment_id)
    return {"ok": True, "count": len(schedules), "schedules": schedules}


def list_schedule_runs(
    context: ToolContext,
    schedule_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Audit log of recent schedule firings."""
    safe_limit = max(1, min(int(limit), 500))
    runs = context.db.list_schedule_runs(
        schedule_id=schedule_id, status=status, limit=safe_limit)
    return {"ok": True, "count": len(runs), "runs": runs}


def create_schedule(
    context: ToolContext,
    name: str,
    action_type: str,
    action_payload: dict[str, Any] | None = None,
    cron_expr: str | None = None,
    starts_at: str | None = None,
    ends_at: str | None = None,
    deployment_id: str = "default",
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Create a scheduled action. Approval-gated — persistent state change.

    Action types:
      set_state, set_deployment_state, enable_rule, disable_rule, webhook.
    Either cron_expr (recurring) or starts_at/ends_at (one-shot window)
    should be provided.
    """
    from clawcam_gateway.scheduler import is_valid_action
    if not name or not name.strip():
        return {"ok": False, "error": "name is required"}
    if not is_valid_action(action_type):
        return {"ok": False, "error": f"invalid action_type: {action_type}"}
    if cron_expr:
        try:
            from croniter import croniter  # type: ignore
            if not croniter.is_valid(cron_expr):
                return {"ok": False, "error": f"invalid cron expression: {cron_expr}"}
        except ImportError:
            return {"ok": False, "error": "croniter not installed; cannot validate cron"}
    schedule_id = f"sched-{uuid.uuid4().hex[:12]}"
    context.db.add_schedule({
        "schedule_id": schedule_id,
        "deployment_id": deployment_id,
        "name": name.strip(),
        "cron_expr": cron_expr,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "action_type": action_type,
        "action_payload": action_payload or {},
        "enabled": True,
    })
    return {
        "ok": True,
        "created": True,
        "schedule": context.db.get_schedule(schedule_id),
        "message": f"Schedule '{name}' created.",
    }


def list_detection_zones(
    context: ToolContext,
    device_id: str | None = None,
    enabled_only: bool = False,
) -> dict[str, Any]:
    """List polygon detection zones, optionally scoped to a device."""
    zones = context.db.list_detection_zones(
        device_id=device_id, enabled_only=enabled_only,
    )
    return {"ok": True, "count": len(zones), "zones": zones}


def create_detection_zone(
    context: ToolContext,
    device_id: str,
    name: str,
    polygon: list[list[float]],
    action: str,
    priority: int = 100,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Create a polygon zone on a camera. Approval-gated (persistent state).

    polygon is a list of [x, y] points in image-normalised coordinates
    (each value 0.0-1.0). action must be one of: alert, record, ignore,
    privacy_mask.
    """
    from clawcam_gateway.zones import is_valid_polygon, is_valid_zone_action
    if not name or not name.strip():
        return {"ok": False, "error": "name is required"}
    if not is_valid_polygon(polygon):
        return {
            "ok": False,
            "error": "polygon must be a list of >=3 [x, y] points with each coord 0-1",
        }
    if not is_valid_zone_action(action):
        return {
            "ok": False,
            "error": f"action must be one of alert, record, ignore, privacy_mask (got {action!r})",
        }
    if context.db.get_device(device_id) is None:
        return {"ok": False, "error": f"unknown device: {device_id}"}
    zone_id = f"zone-{uuid.uuid4().hex[:12]}"
    context.db.add_detection_zone({
        "zone_id": zone_id,
        "device_id": device_id,
        "name": name.strip(),
        "polygon": polygon,
        "action": action,
        "priority": int(priority),
        "enabled": True,
    })
    return {
        "ok": True,
        "created": True,
        "zone": context.db.get_detection_zone(zone_id),
        "message": f"Detection zone '{name}' created on device {device_id}.",
    }


def list_audio_classifications(
    context: ToolContext,
    event_id: str | None = None,
    label: str | None = None,
    species: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return recent audio classifications (BirdNET / glass-break / etc.).

    Audio is captured at devices with profiles that enable it (bird_feeder,
    home_security_*, apiary). Each classifier-hit gets one row with label,
    species, confidence, time offset within the audio file.
    """
    safe_limit = max(1, min(int(limit), 500))
    results = context.db.list_audio_classifications(
        event_id=event_id, label=label, species=species,
        min_confidence=float(min_confidence), limit=safe_limit,
    )
    return {"ok": True, "count": len(results), "results": results}


def get_audio_for_event(context: ToolContext, event_id: str) -> dict[str, Any]:
    """Return all uploaded audio files + their classifications for *event_id*."""
    uploads = context.db.list_audio_uploads(event_id=event_id)
    classifications = context.db.list_audio_classifications(event_id=event_id)
    return {
        "ok": True,
        "event_id": event_id,
        "upload_count": len(uploads),
        "uploads": uploads,
        "classifications": classifications,
    }


def list_detectors(context: ToolContext) -> dict[str, Any]:
    """Return all detectors known to the gateway's registry, with availability."""
    from clawcam_gateway.inference.registry import get_registry
    reg = get_registry()
    return {
        "ok": True,
        "all_detectors": reg.names(),
        "available_detectors": reg.available_names(),
    }


def get_device_detector_chain(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the detector chain that will run on uploads from *device_id*.

    Resolution order: per-device override → profile defaults → mock.
    """
    from clawcam_gateway.inference.orchestrator import InferenceOrchestrator
    device = context.db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}"}
    chain = InferenceOrchestrator(db=context.db).chain_for_device(device_id)
    return {
        "ok": True,
        "device_id": device_id,
        "profile": device.get("profile"),
        "chain": chain,
        "override_set": "detector_chain" in device,
    }


def set_device_detector_chain(
    context: ToolContext,
    device_id: str,
    chain: list[str] | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Set or clear a per-device detector chain override. Approval-gated.

    chain=None resets to profile defaults. List must be detector names from
    the registry (list_detectors); unknown names are stored but will be
    silently skipped by the orchestrator at run-time.
    """
    if chain is not None and not isinstance(chain, list):
        return {"ok": False, "error": "chain must be a list of detector names or null"}
    ok = context.db.set_device_detector_chain(device_id, chain)
    if not ok:
        return {"ok": False, "error": f"unknown device: {device_id}"}
    return {"ok": True, "device_id": device_id, "chain": chain}


def get_event_inference_chain(context: ToolContext, event_id: str) -> dict[str, Any]:
    """Return the full multi-detector chain result for a single event.

    With Phase 12, each event can have multiple inference_results rows
    (one per detector in the chain). This tool returns all of them
    ordered by execution time.
    """
    results = context.db.list_inference_results_for_event(event_id)
    return {"ok": True, "event_id": event_id, "count": len(results), "results": results}


def _validate_config_patch(patch: dict[str, Any]) -> None:
    """Reject patches that reference protected keys."""

    protected = {"device_id", "deployment_id", "firmware", "hardware"}
    bad_keys = protected & set(patch.keys())
    if bad_keys:
        raise ValueError(f"patch must not modify protected keys: {sorted(bad_keys)}")


def _summary_sentence(event_count: int, event_counts: Counter[str], label_counts: Counter[str]) -> str:
    if event_count == 0:
        return "No ClawCam events matched the requested filters."
    common_event = event_counts.most_common(1)[0][0] if event_counts else "event"
    if label_counts:
        common_label, common_label_count = label_counts.most_common(1)[0]
        return f"Found {event_count} event(s), mostly {common_event}; top label is {common_label} ({common_label_count})."
    return f"Found {event_count} event(s), mostly {common_event}; no classifications are available yet."
