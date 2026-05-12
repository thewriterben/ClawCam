"""MCP-style gateway tools for ClawCam brain integrations."""

from clawcam_gateway.tools.clawcam_tools import (
    ToolContext,
    apply_config_patch,
    capture_now,
    generate_daily_summary,
    get_node_health,
    get_recent_detections,
)

__all__ = [
    "ToolContext",
    "apply_config_patch",
    "capture_now",
    "generate_daily_summary",
    "get_node_health",
    "get_recent_detections",
]
