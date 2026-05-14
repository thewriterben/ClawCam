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
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from clawcam_gateway.storage.database import GatewayDatabase


@dataclass(frozen=True)
class ToolContext:
    """Shared context for ClawCam gateway tool calls."""

    database_path: Path | str = "clawcam_gateway.db"

    @property
    def db(self) -> GatewayDatabase:
        return GatewayDatabase(self.database_path)


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

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "status": "queued",
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

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "status": "queued",
        "patch_keys": list(patch.keys()),
        "approval_id": approval_id,
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
