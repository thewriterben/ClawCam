"""Oh-Ben-Claw adapter for ClawCam gateway tools.

This adapter connects an Oh-Ben-Claw brain to the ClawCam gateway by:
  1. Launching the gateway's MCP-compatible stdio bridge as a subprocess.
  2. Discovering tools (legacy: initialize + tools/list; 2026: tools/list
     directly, with optional server/discover).
  3. Enforcing the ClawCam approval policy before dispatching tool calls.
  4. Providing a clean Python API that Oh-Ben-Claw can import and register.

Phase 13 (WS2): supports both MCP lifecycles via ``protocol_mode``:
  - ``"legacy-2024"`` (default): initialize/initialized handshake on connect.
  - ``"stateless-2026"``: no handshake; ``clientInfo`` travels in ``_meta``
    on every request (SEP-2575) and capabilities come from server/discover.
Flip the default when the final 2026-07-28 specification ships.

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

PROTOCOL_MODE_LEGACY = "legacy-2024"
PROTOCOL_MODE_2026 = "stateless-2026"
_PROTOCOL_VERSIONS = {PROTOCOL_MODE_LEGACY: "2024-11-05", PROTOCOL_MODE_2026: "2026-07-28"}
_CLIENT_INFO = {"name": "clawcam-brain-adapter", "version": "0.1.0"}

# Approval scopes (Phase 13 WS6) — shared vocabulary with Oh-Ben-Claw's
# ApprovalScope (call / session / forever).
SCOPE_CALL = "call"
SCOPE_SESSION = "session"
SCOPE_FOREVER = "forever"
APPROVAL_SCOPES = (SCOPE_CALL, SCOPE_SESSION, SCOPE_FOREVER)


class ApprovalGrants:
    """Session + persisted forever approval grants for gated tools.

    Mirrors Oh-Ben-Claw's ForeverGrants: session grants live in memory;
    forever grants persist as JSON so they survive adapter restarts.
    """

    def __init__(self, forever_path: str | Path | None = None):
        self._session: set[str] = set()
        self._forever_path = Path(forever_path) if forever_path else (
            Path.home() / ".clawcam" / "approval_grants.json"
        )
        self._forever: dict[str, str] = self._load_forever()

    def _load_forever(self) -> dict[str, str]:
        try:
            raw = json.loads(self._forever_path.read_text())
            return {g["tool_name"]: g["granted_at"] for g in raw}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _save_forever(self) -> None:
        self._forever_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"tool_name": name, "granted_at": ts}
            for name, ts in sorted(self._forever.items())
        ]
        self._forever_path.write_text(json.dumps(payload, indent=2))

    def grant(self, tool_name: str, scope: str) -> None:
        if scope not in APPROVAL_SCOPES:
            raise ValueError(f"unknown approval scope: {scope!r}")
        if scope == SCOPE_SESSION:
            self._session.add(tool_name)
        elif scope == SCOPE_FOREVER:
            from datetime import datetime, timezone

            self._forever[tool_name] = datetime.now(timezone.utc).isoformat()
            self._save_forever()
        # SCOPE_CALL grants nothing durable by design.

    def is_granted(self, tool_name: str) -> bool:
        return tool_name in self._session or tool_name in self._forever

    def revoke(self, tool_name: str) -> bool:
        revoked = False
        if tool_name in self._session:
            self._session.discard(tool_name)
            revoked = True
        if tool_name in self._forever:
            del self._forever[tool_name]
            self._save_forever()
            revoked = True
        return revoked


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
        "list_audio_classifications",
        "get_audio_for_event",
        "list_detectors",
        "get_device_detector_chain",
        "get_event_inference_chain",
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
        "set_device_detector_chain",
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

    def __init__(self, proc: subprocess.Popen, protocol_mode: str = PROTOCOL_MODE_LEGACY):
        if protocol_mode not in _PROTOCOL_VERSIONS:
            raise ValueError(f"unknown protocol_mode: {protocol_mode!r}")
        self._proc = proc
        self._next_id = 1
        self.protocol_mode = protocol_mode

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        if self.protocol_mode == PROTOCOL_MODE_2026:
            # 2026-07-28: clientInfo travels in _meta on every request
            # (SEP-2575). Preserve caller-set _meta keys.
            params = dict(params or {})
            meta = dict(params.get("_meta") or {})
            meta.setdefault("io.modelcontextprotocol/clientInfo", dict(_CLIENT_INFO))
            params["_meta"] = meta
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
        """Legacy 2024-11-05 handshake (not used in stateless-2026 mode)."""
        return self._send("initialize", {
            "protocolVersion": _PROTOCOL_VERSIONS[PROTOCOL_MODE_LEGACY],
            "clientInfo": dict(_CLIENT_INFO),
            "capabilities": {},
        })

    def discover(self) -> dict[str, Any]:
        """2026-07-28 on-demand capability discovery (SEP-2575)."""
        return self._send("server/discover", {})

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
        protocol_mode: str = PROTOCOL_MODE_LEGACY,
        grants: ApprovalGrants | None = None,
    ):
        if protocol_mode not in _PROTOCOL_VERSIONS:
            raise ValueError(f"unknown protocol_mode: {protocol_mode!r}")
        self._gateway_dir = Path(gateway_dir).resolve()
        self._db_path = Path(db_path)
        self._python = python or sys.executable
        self._policy = policy or ToolPolicy()
        self._protocol_mode = protocol_mode
        self._grants = grants or ApprovalGrants()
        self._approval_audit: list[dict[str, Any]] = []
        self._funnel: dict[str, dict[str, int]] = {}
        self._client: _MCPStdioClient | None = None
        self._tools: list[dict[str, Any]] = []

    @property
    def protocol_mode(self) -> str:
        return self._protocol_mode

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Launch the gateway stdio bridge and establish the MCP connection.

        Legacy mode performs the initialize handshake. Stateless-2026 mode
        sends no handshake (removed in the 2026-07-28 spec); it attempts
        ``server/discover`` for capability info but tolerates servers that
        don't implement it.
        """

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
        self._client = _MCPStdioClient(proc, protocol_mode=self._protocol_mode)
        if self._protocol_mode == PROTOCOL_MODE_LEGACY:
            self._client.initialize()
        else:
            try:
                self._client.discover()
            except RuntimeError:
                pass  # discovery is on-demand, not a lifecycle requirement
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
        scope: str = SCOPE_CALL,
    ) -> dict[str, Any]:
        """Dispatch a ClawCam tool call through the MCP bridge.

        Approval model (Phase 13 WS6 — shared vocabulary with Oh-Ben-Claw):
        a gated tool runs when ``approved=True`` is passed for this call, or
        when a prior ``session``/``forever`` grant covers the tool. Passing
        ``approved=True`` with ``scope="session"`` or ``"forever"`` records a
        durable grant. Every gated decision is appended to the approval audit
        and counted in the funnel.

        Args:
            name: Tool name from the ClawCam tool catalog.
            arguments: Tool arguments dict.
            approved: Explicit human approval for this call.
            scope: Grant scope when approved: "call" (default), "session",
                   or "forever".

        Returns:
            The tool result dict with an 'ok' flag.

        Raises:
            ApprovalRequired: When an approval-gated tool lacks approval/grant.
            ValueError: On an unknown scope.
            RuntimeError: When the adapter is not connected.
        """

        if self._client is None:
            raise RuntimeError("ClawCamAdapter is not connected; call connect() first")
        if scope not in APPROVAL_SCOPES:
            raise ValueError(f"unknown approval scope: {scope!r}")

        args = arguments or {}

        if self._policy.requires_approval(name):
            if approved:
                self._grants.grant(name, scope)
                self._record_approval(name, decision=f"approved_{scope}")
            elif self._grants.is_granted(name):
                self._record_approval(name, decision="granted_prior")
            else:
                self._record_approval(name, decision="denied")
                raise ApprovalRequired(name, args)

        return self._client.call_tool(name, args)

    # ── Approval audit & funnel ────────────────────────────────────────────

    def _record_approval(self, tool_name: str, decision: str) -> None:
        from datetime import datetime, timezone

        self._approval_audit.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "decision": decision,
        })
        counters = self._funnel.setdefault(
            tool_name,
            {"asked": 0, "approved_call": 0, "approved_session": 0,
             "approved_forever": 0, "granted_prior": 0, "denied": 0},
        )
        counters["asked"] += 1
        if decision in counters:
            counters[decision] += 1

    def approval_audit(self) -> list[dict[str, Any]]:
        """Audit entries for gated-tool decisions this adapter lifetime."""
        return list(self._approval_audit)

    def funnel_summary(self) -> dict[str, dict[str, int]]:
        """Per-tool ask/approve/deny counters (approval-gated tools only)."""
        return {k: dict(v) for k, v in self._funnel.items()}

    @property
    def grants(self) -> ApprovalGrants:
        return self._grants

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
