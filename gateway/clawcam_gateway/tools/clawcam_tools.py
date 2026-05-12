"""MCP-style gateway tools for ClawCam brain integrations.

These functions are intentionally plain Python callables so they can be wrapped by an
MCP server, an HTTP endpoint, or an Oh-Ben-Claw tool adapter without duplicating
business logic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
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
    """Generate a small structured summary from recent gateway events.

    This first-pass implementation summarizes stored events only. A later version should
    query observations/classifications directly and include reviewed labels, media links,
    health diagnostics, and model provenance.
    """

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


def capture_now(context: ToolContext, device_id: str, reason: str | None = None) -> dict[str, Any]:
    """Placeholder for approved manual capture requests.

    Manual capture requires node command transport, which is not implemented in Phase 1.
    Returning a structured not-ready response lets brain adapters handle the capability
    safely without pretending the operation exists.
    """

    _ = context
    return {
        "ok": False,
        "requires_approval": True,
        "implemented": False,
        "device_id": device_id,
        "reason": reason,
        "error": "capture_now requires node command transport; planned for Phase 2.",
    }


def apply_config_patch(context: ToolContext, device_id: str, patch: dict[str, Any], approval_id: str | None = None) -> dict[str, Any]:
    """Placeholder for approved configuration changes."""

    _ = context
    return {
        "ok": False,
        "requires_approval": True,
        "implemented": False,
        "device_id": device_id,
        "patch": patch,
        "approval_id": approval_id,
        "error": "apply_config_patch requires policy enforcement and node command transport; planned for a later phase.",
    }


def _summary_sentence(event_count: int, event_counts: Counter[str], label_counts: Counter[str]) -> str:
    if event_count == 0:
        return "No ClawCam events matched the requested filters."
    common_event = event_counts.most_common(1)[0][0] if event_counts else "event"
    if label_counts:
        common_label, common_label_count = label_counts.most_common(1)[0]
        return f"Found {event_count} event(s), mostly {common_event}; top label is {common_label} ({common_label_count})."
    return f"Found {event_count} event(s), mostly {common_event}; no classifications are available yet."
