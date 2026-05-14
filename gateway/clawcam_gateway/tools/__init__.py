"""MCP-style gateway tools for ClawCam brain integrations."""

from clawcam_gateway.tools.clawcam_tools import (
    ToolContext,
    apply_config_patch,
    capture_now,
    generate_daily_summary,
    get_inference_results,
    get_node_health,
    get_recent_detections,
    list_capabilities,
    list_firmware_builds,
    list_pending_commands,
    list_species_detections,
    queue_firmware_update,
)

__all__ = [
    "ToolContext",
    "apply_config_patch",
    "capture_now",
    "generate_daily_summary",
    "get_inference_results",
    "get_node_health",
    "get_recent_detections",
    "list_capabilities",
    "list_firmware_builds",
    "list_pending_commands",
    "list_species_detections",
    "queue_firmware_update",
]
