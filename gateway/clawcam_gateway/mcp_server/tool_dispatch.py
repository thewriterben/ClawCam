"""Small JSON tool dispatcher for ClawCam gateway MCP/server adapters.

This module is not a full MCP server yet. It centralizes tool dispatch so a future MCP
server, HTTP tool endpoint, or Oh-Ben-Claw adapter can share one implementation path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from clawcam_gateway.tools import (
    ToolContext,
    apply_config_patch,
    capture_now,
    export_detections_csv,
    generate_daily_summary,
    get_cloud_sync_status,
    get_inference_results,
    get_node_health,
    get_recent_detections,
    list_capabilities,
    list_firmware_builds,
    list_pending_commands,
    list_species_detections,
    queue_firmware_update,
)


def dispatch_tool(name: str, arguments: dict[str, Any] | None = None, database_path: str | Path = "clawcam_gateway.db", mqtt_bridge=None) -> dict[str, Any]:
    """Dispatch a ClawCam tool call by name.

    Args:
        name: Tool name from the ClawCam tool catalog.
        arguments: JSON-like tool arguments.
        database_path: Gateway database path.
    """

    args = arguments or {}
    context = ToolContext(database_path=database_path, mqtt_bridge=mqtt_bridge)
    dispatch: dict[str, Callable[..., dict[str, Any]]] = {
        "get_recent_detections": lambda **kw: get_recent_detections(context, **kw),
        "get_node_health": lambda **kw: get_node_health(context, **kw),
        "generate_daily_summary": lambda **kw: generate_daily_summary(context, **kw),
        "list_pending_commands": lambda **kw: list_pending_commands(context, **kw),
        "list_capabilities": lambda **kw: list_capabilities(context, **kw),
        "get_inference_results": lambda **kw: get_inference_results(context, **kw),
        "list_species_detections": lambda **kw: list_species_detections(context, **kw),
        "list_firmware_builds": lambda **kw: list_firmware_builds(context, **kw),
        "get_cloud_sync_status": lambda **kw: get_cloud_sync_status(context, **kw),
        "export_detections_csv": lambda **kw: export_detections_csv(context, **kw),
        "capture_now": lambda **kw: capture_now(context, **kw),
        "apply_config_patch": lambda **kw: apply_config_patch(context, **kw),
        "queue_firmware_update": lambda **kw: queue_firmware_update(context, **kw),
    }
    if name not in dispatch:
        return {"ok": False, "error": f"unknown ClawCam tool: {name}", "tool": name}
    try:
        return dispatch[name](**args)
    except TypeError as exc:
        return {"ok": False, "error": f"invalid arguments for {name}: {exc}", "tool": name}
