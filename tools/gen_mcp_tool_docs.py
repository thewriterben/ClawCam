#!/usr/bin/env python3
"""Regenerate `docs/standards/mcp-tools.md` from the MCP tool catalog.

The catalog already has one source of truth in code — `TOOL_DEFINITIONS` +
`APPROVAL_REQUIRED_TOOLS` in `stdio_server.py` — and three consumers derive from
it at runtime (the stdio server, `GET /api/v1/tools`, the Oh-Ben-Claw adapter),
guarded by `tests/gateway/test_tool_catalog_ssot.py`.

Docs were the fourth consumer and the only one still copied by hand, so they
drifted: the generated catalog and three prose files sat at 46 tools while the
code had grown to 57. This script closes that last gap by deriving the doc too,
and `tests/gateway/test_tool_catalog_docs.py` fails the build when the checked-in
file no longer matches.

Reading is deliberately AST-based rather than `import clawcam_gateway...`: the
doc must be regenerable from a bare checkout, without fastapi, torch, or any
other gateway runtime dependency (pre-commit, a docs job, a contributor's
laptop). The SSOT test proves this reading agrees with the module the server
actually runs, so the shortcut costs no fidelity.

Usage:
    python tools/gen_mcp_tool_docs.py            # rewrite the doc
    python tools/gen_mcp_tool_docs.py --check    # exit 1 if the doc is stale
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PY = REPO_ROOT / "gateway" / "clawcam_gateway" / "mcp_server" / "stdio_server.py"
DOC_PATH = REPO_ROOT / "docs" / "standards" / "mcp-tools.md"

_WANTED = ("TOOL_DEFINITIONS", "APPROVAL_REQUIRED_TOOLS")


def load_catalog(server_py: Path = SERVER_PY) -> tuple[list[dict], set[str]]:
    """Return `(tool_definitions, approval_required)` read out of the source.

    Both names are module-level literals (`APPROVAL_REQUIRED_TOOLS` wrapped in a
    `frozenset(...)` call), so `ast.literal_eval` is enough and no import — and
    therefore no dependency — is needed.
    """
    tree = ast.parse(server_py.read_text(encoding="utf-8"))
    found: dict[str, object] = {}

    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        name = getattr(target, "id", None)
        if name not in _WANTED or value is None:
            continue
        # frozenset({...}) / set({...}) — unwrap to the literal argument.
        if isinstance(value, ast.Call) and len(value.args) == 1:
            value = value.args[0]
        found[name] = ast.literal_eval(value)

    missing = [n for n in _WANTED if n not in found]
    if missing:
        raise SystemExit(
            f"{server_py}: could not read {', '.join(missing)} as a module-level "
            "literal. If the catalog moved or became computed, update "
            "tools/gen_mcp_tool_docs.py to match."
        )

    tools = list(found["TOOL_DEFINITIONS"])  # type: ignore[arg-type]
    approval = set(found["APPROVAL_REQUIRED_TOOLS"])  # type: ignore[arg-type]
    return tools, approval


def _cell(text: str) -> str:
    """Make a description safe for a one-line markdown table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _table(tools: list[dict]) -> list[str]:
    rows = ["| Tool | Description |", "|---|---|"]
    for tool in sorted(tools, key=lambda t: t["name"]):
        rows.append(f"| `{tool['name']}` | {_cell(tool.get('description', ''))} |")
    return rows


def render(tools: list[dict], approval_required: set[str]) -> str:
    """Render the full document. Deterministic — no timestamp.

    The previous hand-maintained version carried a generated-on date. A date in
    generated output makes every regeneration a diff and every check a false
    alarm, so the provenance line names the generator instead.
    """
    gated = [t for t in tools if t["name"] in approval_required]
    reads = [t for t in tools if t["name"] not in approval_required]

    lines = [
        "# ClawCam MCP Tool Catalog",
        "",
        "> **Generated from code** by `tools/gen_mcp_tool_docs.py`, which reads",
        "> `TOOL_DEFINITIONS` + `APPROVAL_REQUIRED_TOOLS` out of",
        "> `gateway/clawcam_gateway/mcp_server/stdio_server.py`. Do not hand-edit —",
        "> `tests/gateway/test_tool_catalog_docs.py` regenerates this file and fails",
        "> if it differs. Those same two names back the MCP stdio server,",
        "> `GET /api/v1/tools`, and the Oh-Ben-Claw adapter.",
        "",
        f"**{len(tools)} tools total: {len(reads)} auto-approved reads, "
        f"{len(gated)} approval-gated writes.**",
        "",
        "The stdio server speaks two protocol lifecycles: `legacy-2024` and `2026-07-28`.",
        "No MCP resources are currently implemented (tools only).",
        "",
        "## Approval-gated tools (write scope required)",
        "",
        "These mutate device or gateway state. Via the REST bridge (`POST /api/v1/tools/{name}`)",
        "they require an API key with `write` scope when auth is enabled; via the Oh-Ben-Claw",
        "adapter they always prompt for approval.",
        "",
        *_table(gated),
        "",
        "## Auto-approved read tools",
        "",
        *_table(reads),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the checked-in doc is stale",
    )
    args = parser.parse_args(argv)

    expected = render(*load_catalog())
    current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else None

    if args.check:
        if current == expected:
            print(f"{DOC_PATH.relative_to(REPO_ROOT)} is up to date.")
            return 0
        print(
            f"{DOC_PATH.relative_to(REPO_ROOT)} is stale. "
            "Run: python tools/gen_mcp_tool_docs.py",
            file=sys.stderr,
        )
        return 1

    if current == expected:
        print(f"{DOC_PATH.relative_to(REPO_ROOT)} already up to date.")
        return 0

    # newline="\n": the doc is LF in the repo, and the regenerate-and-compare
    # check must not turn "generated on Windows" into a diff.
    DOC_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {DOC_PATH.relative_to(REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
