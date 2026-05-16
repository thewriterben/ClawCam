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
    create_alert_rule,
    create_detection_zone,
    create_schedule,
    export_detections_csv,
    generate_daily_summary,
    get_audio_for_event,
    get_device_detector_chain,
    get_event_inference_chain,
    get_cloud_sync_status,
    get_device_state,
    get_inference_results,
    get_node_health,
    get_recent_detections,
    list_alert_rules,
    list_audio_classifications,
    list_capabilities,
    list_detectors,
    list_detection_zones,
    list_firmware_builds,
    list_pending_commands,
    list_profiles,
    list_recent_alerts,
    list_schedule_runs,
    list_schedules,
    list_species_detections,
    list_state_transitions,
    queue_firmware_update,
    set_deployment_state,
    set_device_detector_chain,
    set_device_state,
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
        "list_alert_rules": lambda **kw: list_alert_rules(context, **kw),
        "list_recent_alerts": lambda **kw: list_recent_alerts(context, **kw),
        "create_alert_rule": lambda **kw: create_alert_rule(context, **kw),
        "list_profiles": lambda **kw: list_profiles(context, **kw),
        "get_device_state": lambda **kw: get_device_state(context, **kw),
        "list_state_transitions": lambda **kw: list_state_transitions(context, **kw),
        "set_device_state": lambda **kw: set_device_state(context, **kw),
        "set_deployment_state": lambda **kw: set_deployment_state(context, **kw),
        "list_schedules": lambda **kw: list_schedules(context, **kw),
        "list_schedule_runs": lambda **kw: list_schedule_runs(context, **kw),
        "create_schedule": lambda **kw: create_schedule(context, **kw),
        "list_detection_zones": lambda **kw: list_detection_zones(context, **kw),
        "create_detection_zone": lambda **kw: create_detection_zone(context, **kw),
        "list_audio_classifications": lambda **kw: list_audio_classifications(context, **kw),
        "get_audio_for_event": lambda **kw: get_audio_for_event(context, **kw),
        "list_detectors": lambda **kw: list_detectors(context, **kw),
        "get_device_detector_chain": lambda **kw: get_device_detector_chain(context, **kw),
        "get_event_inference_chain": lambda **kw: get_event_inference_chain(context, **kw),
        "set_device_detector_chain": lambda **kw: set_device_detector_chain(context, **kw),
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
