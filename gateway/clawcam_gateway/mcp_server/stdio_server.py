"""Lightweight JSON-RPC stdio server for ClawCam gateway tools.

This module implements the subset of the Model Context Protocol message flow that is
needed for ClawCam's first agent integration surface: initialize, tools/list, and
tools/call. It intentionally avoids adding a hard dependency on a specific MCP SDK while
keeping the wire shape close to MCP-compatible JSON-RPC clients.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from clawcam_gateway.mcp_server.tool_dispatch import dispatch_tool

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "clawcam-gateway"
SERVER_VERSION = "0.1.0"


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_recent_detections",
        "description": "Return recent ClawCam event/detection records from the gateway database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}
            },
        },
    },
    {
        "name": "get_node_health",
        "description": "Return the latest health payload for a ClawCam node.",
        "inputSchema": {
            "type": "object",
            "required": ["device_id"],
            "properties": {"device_id": {"type": "string"}},
        },
    },
    {
        "name": "generate_daily_summary",
        "description": "Generate a structured summary from recent gateway events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_date": {"type": "string", "description": "Optional ISO date YYYY-MM-DD."},
                "deployment_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
        },
    },
    {
        "name": "list_pending_commands",
        "description": "Return commands queued for field nodes (captures, config patches). Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Filter by device ID."},
                "status": {"type": "string", "enum": ["queued", "delivered", "executed", "failed"],
                           "description": "Filter by command status."},
            },
        },
    },
    {
        "name": "list_capabilities",
        "description": "Return the ESP-Claw capability groups declared by a ClawCam node.",
        "inputSchema": {
            "type": "object",
            "required": ["device_id"],
            "properties": {"device_id": {"type": "string"}},
        },
    },
    {
        "name": "get_inference_results",
        "description": "Return species detection results for a specific captured event.",
        "inputSchema": {
            "type": "object",
            "required": ["event_id"],
            "properties": {"event_id": {"type": "string"}},
        },
    },
    {
        "name": "list_species_detections",
        "description": "List recent inference results with optional filtering by label, species, or confidence. Useful for 'what animals were detected?' queries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
                "label": {"type": "string", "enum": ["animal", "person", "vehicle"],
                          "description": "Filter by detection category."},
                "min_confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                "species": {"type": "string", "description": "Substring match on species name."},
            },
        },
    },
    {
        "name": "list_firmware_builds",
        "description": "List all firmware binaries uploaded to the gateway, with build_id, version, SHA256, and download URL.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_cloud_sync_status",
        "description": "Return cloud upload status for gateway media files. Shows how many images are pending, uploaded, or failed for off-site archival.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
                "status": {"type": "string", "enum": ["pending", "uploaded", "failed"],
                           "description": "Filter by upload status."},
                "event_id": {"type": "string", "description": "Filter to a specific event."},
            },
        },
    },
    {
        "name": "export_detections_csv",
        "description": "Export recent inference detection results as a CSV string. Useful for downloading structured detection data for analysis or reporting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 1000},
                "label": {"type": "string", "enum": ["animal", "person", "vehicle"],
                          "description": "Filter by detection category."},
                "min_confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.0},
                "species": {"type": "string", "description": "Substring match on species name."},
            },
        },
    },
    {
        "name": "capture_now",
        "description": "Request a manual capture from a reachable ClawCam node. Approval-gated; requires cap_clawcam_camera_trap.",
        "inputSchema": {
            "type": "object",
            "required": ["device_id"],
            "properties": {"device_id": {"type": "string"}, "reason": {"type": "string"}},
        },
    },
    {
        "name": "apply_config_patch",
        "description": "Apply an approved configuration patch to a node. Approval-gated; patch is queued for node pickup.",
        "inputSchema": {
            "type": "object",
            "required": ["device_id", "patch"],
            "properties": {
                "device_id": {"type": "string"},
                "patch": {"type": "object"},
                "approval_id": {"type": "string"},
            },
        },
    },
    {
        "name": "queue_firmware_update",
        "description": "Queue an OTA firmware update for a ClawCam node. Approval-gated; requires cap_clawcam_firmware_ota. Node downloads and verifies SHA256 before flashing.",
        "inputSchema": {
            "type": "object",
            "required": ["device_id", "build_id"],
            "properties": {
                "device_id": {"type": "string"},
                "build_id": {"type": "string", "description": "Build ID from list_firmware_builds."},
                "approval_id": {"type": "string"},
            },
        },
    },
]


class ClawCamMCPServer:
    """Minimal JSON-RPC request handler for ClawCam gateway tools."""

    def __init__(self, database_path: str | Path = "clawcam_gateway.db"):
        self.database_path = Path(database_path)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a JSON-RPC request or notification.

        Notifications do not include an `id` and therefore do not receive a response.
        """

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        try:
            if method == "initialize":
                result = self._initialize()
            elif method == "tools/list":
                result = {"tools": TOOL_DEFINITIONS}
            elif method == "tools/call":
                result = self._tool_call(params)
            elif method == "ping":
                result = {}
            elif request_id is None:
                return None
            else:
                return self._error(request_id, -32601, f"method not found: {method}")
        except Exception as exc:  # noqa: BLE001 - server must return JSON-RPC errors
            if request_id is None:
                return None
            return self._error(request_id, -32603, str(exc))

        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _tool_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            raise ValueError("tools/call requires a non-empty string parameter: name")
        if not isinstance(arguments, dict):
            raise ValueError("tools/call arguments must be an object")

        result = dispatch_tool(name, arguments, database_path=self.database_path)
        is_error = not bool(result.get("ok", False))
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, indent=2, sort_keys=True),
                }
            ],
            "isError": is_error,
        }

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve_stdio(
    database_path: str | Path = "clawcam_gateway.db",
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """Serve newline-delimited JSON-RPC over stdio."""

    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    server = ClawCamMCPServer(database_path=database_path)

    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = server.handle_request(request)
        except json.JSONDecodeError as exc:
            response = ClawCamMCPServer._error(None, -32700, f"parse error: {exc}")
        if response is not None:
            output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
            output_stream.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ClawCam gateway MCP-compatible stdio server.")
    parser.add_argument("--db", default="clawcam_gateway.db", help="SQLite gateway database path.")
    args = parser.parse_args()
    serve_stdio(database_path=args.db)


if __name__ == "__main__":
    main()
