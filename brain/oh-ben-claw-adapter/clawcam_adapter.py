"""Oh-Ben-Claw adapter for ClawCam gateway tools.

This adapter connects an Oh-Ben-Claw brain to the ClawCam gateway by:
  1. Launching the gateway's MCP-compatible stdio bridge as a subprocess.
  2. Calling initialize + tools/list to discover available tools.
  3. Enforcing the ClawCam approval policy before dispatching tool calls.
  4. Providing a clean Python API that Oh-Ben-Claw can import and register.

Usage:
    adapter = ClawCamAdapter(gateway_dir="./gateway", db_path="../clawcam_gateway.db")
    adapter.connect()
    tools = adapter.list_tools()
    result = adapter.call_tool("get_recent_detections", {"limit": 10})
    adapter.close()

Or as a context manager:
    with ClawCamAdapter(...) as adapter:
        result = adapter.call_tool("generate_daily_summary", {})
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Policy ────────────────────────────────────────────────────────────────

@dataclass
class ToolPolicy:
    """Approval policy for ClawCam tools.

    Tools in auto_approve are called immediately.
    Tools in always_ask raise ApprovalRequired unless called with approved=True.
    """

    auto_approve: frozenset[str] = field(default_factory=lambda: frozenset({
        "get_recent_detections",
        "get_node_health",
        "generate_daily_summary",
        "list_pending_commands",
        "list_capabilities",
        "get_inference_results",
        "list_species_detections",
        "list_firmware_builds",
        "get_cloud_sync_status",
        "export_detections_csv",
        "list_alert_rules",
        "list_recent_alerts",
        "list_profiles",
        "get_device_state",
        "list_state_transitions",
        "list_schedules",
        "list_schedule_runs",
        "list_detection_zones",
    }))
    always_ask: frozenset[str] = field(default_factory=lambda: frozenset({
        "capture_now",
        "apply_config_patch",
        "queue_firmware_update",
        "create_alert_rule",
        "set_device_state",
        "set_deployment_state",
        "create_schedule",
        "create_detection_zone",
    }))

    def requires_approval(self, tool_name: str) -> bool:
        return tool_name in self.always_ask

    def is_auto_approved(self, tool_name: str) -> bool:
        return tool_name in self.auto_approve


class ApprovalRequired(Exception):
    """Raised when a tool call requires explicit human approval."""

    def __init__(self, tool_name: str, arguments: dict[str, Any]):
        self.tool_name = tool_name
        self.arguments = arguments
        super().__init__(
            f"Tool '{tool_name}' requires human approval before calling. "
            f"Pass approved=True after obtaining explicit user confirmation."
        )


# ── MCP stdio client ───────────────────────────────────────────────────────

class _MCPStdioClient:
    """Minimal JSON-RPC client over a subprocess stdio pipe.

    Sends newline-delimited JSON requests and reads newline-delimited responses.
    Stateless: each call writes one request and reads one response.
    """

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._next_id = 1

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        line = json.dumps(request, separators=(",", ":")) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

        raw = self._proc.stdout.readline()
        if not raw:
            raise IOError("MCP stdio bridge closed unexpectedly")
        response = json.loads(raw)
        if "error" in response:
            err = response["error"]
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return response.get("result", {})

    def initialize(self) -> dict[str, Any]:
        return self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "clawcam-brain-adapter", "version": "0.1.0"},
            "capabilities": {},
        })

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._send("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._send("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return result

    def ping(self) -> bool:
        try:
            self._send("ping")
            return True
        except Exception:
            return False

    def close(self) -> None:
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()


# ── Adapter ────────────────────────────────────────────────────────────────

class ClawCamAdapter:
    """Oh-Ben-Claw adapter that connects to a ClawCam gateway via MCP stdio.

    Args:
        gateway_dir: Path to the gateway Python package root (contains clawcam_gateway/).
        db_path: Path to the SQLite gateway database.
        python: Python executable to use (defaults to sys.executable).
        policy: Tool approval policy (defaults to standard ClawCam policy).
    """

    def __init__(
        self,
        gateway_dir: str | Path = "./gateway",
        db_path: str | Path = "../clawcam_gateway.db",
        python: str | None = None,
        policy: ToolPolicy | None = None,
    ):
        self._gateway_dir = Path(gateway_dir).resolve()
        self._db_path = Path(db_path)
        self._python = python or sys.executable
        self._policy = policy or ToolPolicy()
        self._client: _MCPStdioClient | None = None
        self._tools: list[dict[str, Any]] = []

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Launch the gateway stdio bridge and perform MCP initialization."""

        proc = subprocess.Popen(
            [
                self._python,
                "-m", "clawcam_gateway.mcp_server.stdio_server",
                "--db", str(self._db_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self._gateway_dir,
            env=self._subprocess_env(),
        )
        self._client = _MCPStdioClient(proc)
        self._client.initialize()
        self._tools = self._client.list_tools()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._tools = []

    def __enter__(self) -> "ClawCamAdapter":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Tool interface ─────────────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the tools discovered from the gateway, annotated with policy."""

        annotated = []
        for tool in self._tools:
            name = tool.get("name", "")
            annotated.append({
                **tool,
                "approval_required": self._policy.requires_approval(name),
                "auto_approved": self._policy.is_auto_approved(name),
            })
        return annotated

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Dispatch a ClawCam tool call through the MCP bridge.

        Args:
            name: Tool name from the ClawCam tool catalog.
            arguments: Tool arguments dict.
            approved: Set True after obtaining explicit human approval for
                      approval-gated tools. Raises ApprovalRequired otherwise.

        Returns:
            The tool result dict with an 'ok' flag.

        Raises:
            ApprovalRequired: When an approval-gated tool is called without approved=True.
            RuntimeError: When the adapter is not connected.
        """

        if self._client is None:
            raise RuntimeError("ClawCamAdapter is not connected; call connect() first")

        args = arguments or {}

        if self._policy.requires_approval(name) and not approved:
            raise ApprovalRequired(name, args)

        return self._client.call_tool(name, args)

    def ping(self) -> bool:
        """Return True if the gateway stdio bridge is responsive."""
        return self._client is not None and self._client.ping()

    # ── Oh-Ben-Claw registration helper ───────────────────────────────────

    def as_obc_tool_entries(self) -> list[dict[str, Any]]:
        """Return tool definitions in a shape compatible with Oh-Ben-Claw's tool registry.

        Each entry follows the McpToolEntry shape used by Oh-Ben-Claw's McpRegistry:
          {name, description, input_schema, approval_required, source}
        """

        entries = []
        for tool in self._tools:
            name = tool.get("name", "")
            entries.append({
                "name": name,
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", {}),
                "approval_required": self._policy.requires_approval(name),
                "source": "clawcam-gateway",
            })
        return entries

    # ── Internal ──────────────────────────────────────────────────────────

    def _subprocess_env(self) -> dict[str, str]:
        import os
        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH", "")
        gateway_str = str(self._gateway_dir)
        if gateway_str not in pythonpath:
            env["PYTHONPATH"] = f"{gateway_str}{os.pathsep}{pythonpath}" if pythonpath else gateway_str
        return env
