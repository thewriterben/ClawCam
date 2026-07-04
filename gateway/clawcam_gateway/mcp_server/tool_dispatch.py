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
    apply_profile_alert_rules,
    capture_now,
    create_alert_rule,
    create_detection_zone,
    create_schedule,
    export_detections_csv,
    generate_daily_summary,
    get_activity_report,
    get_audio_for_event,
    get_device_detector_chain,
    get_event_inference_chain,
    get_cloud_sync_status,
    get_comparison_report,
    get_device_state,
    get_diversity_report,
    get_encounter_report,
    get_fused_detections,
    get_inference_results,
    get_node_health,
    get_recent_detections,
    get_site_report,
    get_trend_report,
    list_alert_rules,
    list_audio_classifications,
    list_capabilities,
    list_detectors,
    list_detection_zones,
    list_firmware_builds,
    list_observations_for_review,
    list_pending_commands,
    list_profile_alert_templates,
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
    set_review_state,
)


def dispatch_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    database_path: str | Path = "clawcam_gateway.db",
    mqtt_bridge=None,
    source: str = "unknown",
) -> dict[str, Any]:
    """Dispatch a ClawCam tool call by name.

    Every dispatch is recorded in the ``tool_call_audit`` table (Phase 13 WS5):
    timestamp, tool, SHA-256 of the arguments, caller ``source``, ok flag, and
    latency. Audit failures never block the tool call.

    Args:
        name: Tool name from the ClawCam tool catalog.
        arguments: JSON-like tool arguments.
        database_path: Gateway database path.
        source: Caller surface ("mcp-stdio", "rest", "unknown").
    """

    import hashlib
    import json as _json
    import time
    from datetime import datetime, timezone

    args = arguments or {}
    _t0 = time.monotonic()

    def _audit(result_ok: bool) -> None:
        try:
            from clawcam_gateway.storage.database import GatewayDatabase

            args_hash = hashlib.sha256(
                _json.dumps(args, sort_keys=True, default=str).encode()
            ).hexdigest()
            GatewayDatabase(database_path).record_tool_call_audit(
                tool_name=name,
                args_sha256=args_hash,
                source=source,
                ok=result_ok,
                duration_ms=int((time.monotonic() - _t0) * 1000),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:  # noqa: BLE001 - audit must never block dispatch
            pass
    context = ToolContext(database_path=database_path, mqtt_bridge=mqtt_bridge)
    dispatch: dict[str, Callable[..., dict[str, Any]]] = {
        "get_recent_detections": lambda **kw: get_recent_detections(context, **kw),
        "get_node_health": lambda **kw: get_node_health(context, **kw),
        "generate_daily_summary": lambda **kw: generate_daily_summary(context, **kw),
        "list_pending_commands": lambda **kw: list_pending_commands(context, **kw),
        "list_capabilities": lambda **kw: list_capabilities(context, **kw),
        "get_inference_results": lambda **kw: get_inference_results(context, **kw),
        "get_activity_report": lambda **kw: get_activity_report(context, **kw),
        "get_trend_report": lambda **kw: get_trend_report(context, **kw),
        "get_site_report": lambda **kw: get_site_report(context, **kw),
        "get_diversity_report": lambda **kw: get_diversity_report(context, **kw),
        "get_comparison_report": lambda **kw: get_comparison_report(context, **kw),
        "get_encounter_report": lambda **kw: get_encounter_report(context, **kw),
        "get_fused_detections": lambda **kw: get_fused_detections(context, **kw),
        "list_species_detections": lambda **kw: list_species_detections(context, **kw),
        "list_observations_for_review": lambda **kw: list_observations_for_review(context, **kw),
        "set_review_state": lambda **kw: set_review_state(context, **kw),
        "list_firmware_builds": lambda **kw: list_firmware_builds(context, **kw),
        "get_cloud_sync_status": lambda **kw: get_cloud_sync_status(context, **kw),
        "export_detections_csv": lambda **kw: export_detections_csv(context, **kw),
        "list_alert_rules": lambda **kw: list_alert_rules(context, **kw),
        "list_recent_alerts": lambda **kw: list_recent_alerts(context, **kw),
        "create_alert_rule": lambda **kw: create_alert_rule(context, **kw),
        "list_profiles": lambda **kw: list_profiles(context, **kw),
        "list_profile_alert_templates": lambda **kw: list_profile_alert_templates(context, **kw),
        "apply_profile_alert_rules": lambda **kw: apply_profile_alert_rules(context, **kw),
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
        result = {"ok": False, "error": f"unknown ClawCam tool: {name}", "tool": name}
        _audit(False)
        return result
    try:
        result = dispatch[name](**args)
    except TypeError as exc:
        result = {"ok": False, "error": f"invalid arguments for {name}: {exc}", "tool": name}
    _audit(bool(result.get("ok", False)))
    return result
