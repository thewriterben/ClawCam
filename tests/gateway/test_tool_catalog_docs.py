"""S0 drift guard, docs half: the written catalog matches the code catalog.

`test_tool_catalog_ssot.py` pins the three *runtime* consumers of
`TOOL_DEFINITIONS` (MCP server, `GET /api/v1/tools`, brain adapter) to each
other. Docs were the fourth consumer and the only one still copied by hand — so
they drifted exactly the way the code once did: `docs/standards/mcp-tools.md`
and three prose files all said 46 tools while the server advertised 57.

A count in prose is not decoration. It is the number a reader uses to decide
whether their client sees the whole surface, and a stale one sends them looking
for a bug that isn't there.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "tools" / "gen_mcp_tool_docs.py"
GENERATED_DOC = REPO_ROOT / "docs" / "standards" / "mcp-tools.md"

# Live docs that quote catalog sizes. AUDIT_2026-07-04.md is deliberately absent:
# it is a dated record of what was true that day, not a claim about today.
PROSE_DOCS = (
    REPO_ROOT / "gateway" / "README.md",
    REPO_ROOT / "gateway" / "clawcam_gateway" / "mcp_server" / "README.md",
    REPO_ROOT / "docs" / "integration" / "oh-ben-claw-mcp.md",
)


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_mcp_tool_docs", GENERATOR)
    assert spec and spec.loader, f"cannot load {GENERATOR}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


def test_generated_catalog_is_current(gen):
    """Regenerate in memory and compare — the doc is output, not input."""
    expected = gen.render(*gen.load_catalog())
    assert GENERATED_DOC.read_text(encoding="utf-8") == expected, (
        "docs/standards/mcp-tools.md is stale. "
        "Run: python tools/gen_mcp_tool_docs.py"
    )


def test_the_generator_reads_what_the_server_runs(gen):
    """The generator parses the source instead of importing it, so that it works
    without the gateway's runtime deps. This is the test that keeps the shortcut
    honest: the parsed catalog must equal the imported one, name for name."""
    from clawcam_gateway.mcp_server.stdio_server import (
        APPROVAL_REQUIRED_TOOLS,
        TOOL_DEFINITIONS,
    )

    parsed_tools, parsed_approval = gen.load_catalog()
    assert [t["name"] for t in parsed_tools] == [t["name"] for t in TOOL_DEFINITIONS]
    assert parsed_approval == set(APPROVAL_REQUIRED_TOOLS)
    assert [t.get("description") for t in parsed_tools] == [
        t.get("description") for t in TOOL_DEFINITIONS
    ]


@pytest.mark.parametrize("doc", PROSE_DOCS, ids=lambda p: p.name)
def test_prose_docs_quote_the_real_counts(doc, gen):
    """Any 'N tools' / 'N auto-approved' / 'N approval-gated' figure in a live
    doc must be the current figure. Whitespace-tolerant: these phrases wrap."""
    tools, approval = gen.load_catalog()
    expected = {
        r"tools": len(tools),
        r"auto-approved": len(tools) - len(approval),
        r"approval-gated": len(approval),
        r"gated": len(approval),
    }

    text = doc.read_text(encoding="utf-8")
    checked = 0
    for phrase, want in expected.items():
        for match in re.finditer(rf"(\d+)\s+{phrase}\b", text):
            checked += 1
            assert int(match.group(1)) == want, (
                f"{doc.relative_to(REPO_ROOT)} says "
                f"'{match.group(0)}' but the catalog has {want}"
            )

    assert checked, (
        f"{doc.relative_to(REPO_ROOT)} no longer quotes any catalog count — "
        "either the prose changed or this guard is watching the wrong file"
    )
