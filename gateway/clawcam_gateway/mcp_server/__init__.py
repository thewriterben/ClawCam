"""MCP-compatible interfaces for ClawCam gateway tools."""

from clawcam_gateway.mcp_server.stdio_server import (
    ClawCamMCPServer,
    TOOL_DEFINITIONS,
    serve_stdio,
)

__all__ = ["ClawCamMCPServer", "TOOL_DEFINITIONS", "serve_stdio"]
