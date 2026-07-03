# Next Phase Plan — Production Hardening (ClawCam Phase 13 ⇄ Oh-Ben-Claw Phase 15)

**Status:** in progress · **Window:** June 8 – July 31, 2026
**Referenced by:** `ClawCam/docs/ROADMAP.md` (Phase 13) and `Oh-Ben-Claw/ROADMAP.md` (Phase 15)

ClawCam and Oh-Ben-Claw (OBC) run one coordinated hardening phase rather than two
independent ones. Neither side adds product surface area; the goal is to make the
existing phases trustworthy — protocol conformance against the specs as they
actually shipped, an evaluation/observability layer, and an approval model whose
vocabulary and semantics are *identical* across the brain (OBC, Rust) and the
camera gateway (ClawCam, Python). This document is the single place where that
shared contract is written down so the two repos cannot drift.

---

## Why lockstep

OBC is the brain; ClawCam is one of its embodied subsystems, reached over the MCP
stdio bridge (`brain ↔ clawcam_adapter ↔ stdio_server ↔ gateway`). Anything that
crosses that boundary — the MCP wire protocol, the tool catalog, and the approval
model — must mean the same thing on both ends. Three contracts are therefore
defined once and implemented twice:

1. **Tool catalog** — one source of truth per repo, drift-guarded by tests.
2. **MCP protocol mode** — both sides negotiate legacy-2024 vs. stateless-2026.
3. **Approval model** — scope vocabulary + plan-mode argument bounds, wire-compatible.

---

## Shared contract: the approval model

The authoritative definition lives in OBC at `src/approval/mod.rs`; ClawCam mirrors
it in `brain/oh-ben-claw-adapter/clawcam_adapter.py`. The two implementations are
kept behaviorally identical and JSON-wire-compatible (a plan authored on the brain
side validates byte-for-byte on the adapter side).

### Approval scopes

| Scope | Lifetime | OBC (`ApprovalScope`) | ClawCam (`ApprovalGrants` / `call_tool(scope=…)`) |
|----------|------------------------------|-----------------------|----------------------------------------------------|
| `call` | this single invocation | ✅ | ✅ |
| `session`| rest of the process session | ✅ | ✅ (in-memory) |
| `forever`| persisted across restarts | ✅ `~/.oh-ben-claw/approval_grants.json` | ✅ `~/.clawcam/approval_grants.json` |

### Plan-mode approval (argument bounds)

A multi-step plan is approved **once** (tools + per-argument bounds shown to the
operator), then execution is checked **step by step**. The first violation revokes
the entire plan — *halt on drift*; subsequent calls fail `unknown_plan` and must
obtain fresh approval.

| Element | Shape | OBC | ClawCam |
|------------------|------------------------------------------------------------|-----|---------|
| `ArgumentBound` | `{"kind": "exact"\|"one_of"\|"range"\|"any", …}` | ✅ | ✅ |
| `PlanStep` | `{tool_name, bounds: {arg → bound}, deny_unlisted_args}` | ✅ | ✅ |
| `ApprovedPlan` | `{plan_id, steps, created_at, cursor}` | ✅ | ✅ |
| Halt-on-drift | first violation revokes the plan | ✅ | ✅ |
| Funnel counters | asked / approved-by-scope / denied / plan_violations | ✅ | ✅ |

Bound semantics (both sides): `range` rejects non-numbers and booleans; a *bounded
but absent* argument key is out of bounds unless its bound is `any`;
`deny_unlisted_args` rejects any argument key the step did not list.

---

## ClawCam Phase 13 — deliverables & status

| Deliverable | Acceptance | Status |
|----------------------------|-----------------------------------------------------------------------------------------------|--------|
| Tool-catalog SSOT | `stdio_server.TOOL_DEFINITIONS` + `APPROVAL_REQUIRED_TOOLS` are canonical; `GET /api/v1/tools` and the adapter `ToolPolicy` derive from them; drift guarded by `tests/gateway/test_tool_catalog_ssot.py`. | ✅ Done |
| MCP 2026-07-28 readiness | Dual lifecycle behind `protocol_mode` (`legacy-2024` / `stateless-2026`); `_meta` clientInfo (SEP-2575); cross-repo integration suite passes in both modes. | 🔶 In progress (dual-mode + cross-repo suite ✅ 17/17; only the Jul 28 default-flip remains) |
| Evaluation harness | Golden flows on MockDetector + full policy-partition eval; `tests/evals` in pytest testpaths = CI release gate. | ✅ Done (7/7) |
| Observability | `tool_call_audit` at the dispatch chokepoint; `GET /api/v1/metrics`; `GET /api/v1/tool-audit`. | ✅ Done |
| Approval-model upgrade | call/session/forever scopes (WS6); **plan-mode approval with argument bounds honored by `ClawCamAdapter`**; approval audit + funnel. | ✅ Done |

## Oh-Ben-Claw Phase 15 — deliverables & status

| Deliverable | Status |
|----------------------------|--------|
| Skill-install security (ClawHub: consent, checksum, pinning, static flagging, audit) | ✅ Done |
| MCP 2026-07-28 readiness (audit, dual-mode, cross-repo test, flip default Jul 28) | 🔶 Planned |
| A2A v1.0 conformance | ✅ Done |
| Evaluation harness (`tests/evals.rs`, CI gate) | ✅ Done |
| Observability / AgentOps (agent spans, approval-ask counters; cost summary → Phase 16) | ✅ Done (cost deferred) |
| Approval-model upgrade (scopes, plan-mode, shared vocab, funnel) | ✅ Done |

---

## The one remaining joint deliverable: cross-repo MCP integration ✅ built

Both ROADMAPs left a single shared item open — a **cross-repo integration test**
exercising `brain ↔ adapter ↔ stdio bridge ↔ gateway` in *both* protocol modes,
proving the MCP surface works behind plain HTTP with no session affinity (the
stateless-2026 requirement). This is the gate for flipping the default protocol
mode on July 28, 2026.

**Status:** built and green — `tests/integration/test_phase15_cross_repo_mcp.py`
(17 tests). What it asserts:
- The gateway stdio bridge is driven through `ClawCamAdapter` in **both**
  `legacy-2024` and `stateless-2026` modes; discovery serves the identical full
  catalog, an auto-approved read succeeds, and a gated write is authorized two
  ways — scope grant and **plan-mode** — in each mode.
- **No session affinity, stdio:** a bare `tools/call` works with no `initialize`
  handshake; requests are order-independent; two independent server instances on
  the same DB are interchangeable.
- **No session affinity, plain HTTP:** a tool POST works as the very first
  request, sets no session cookie, and two fresh clients (no shared cookie jar)
  are interchangeable and match the MCP catalog.

**Remaining:** only the calendar action — flip the default `protocol_mode` from
`legacy-2024` to `stateless-2026` once the final spec ships on **July 28, 2026**,
and run the same suite to confirm the flipped default.

---

## Embodied integration (OBC-side, built)

Beyond the MCP/approval contract above, OBC now consumes ClawCam as a full
**bidirectional embodied subsystem** on its world-memory substrate (OBC `src/vision/`,
config-gated, default off). Recorded here so the two repos stay in lockstep on what
crosses the bridge.

**Read (ClawCam → OBC):**
- *Detections* → `vision.subject.{species}` facts + a rolling `vision.count.{subject}`
  the OBC foresight layer trends (detection-rate prediction).
- *`get_node_health`* (`poll_health`) → namespaced `clawcam.node.{id}` facts —
  intentionally **not** merged into OBC's own robot power/comms suites (a camera is a
  distinct body).
- *`list_audio_classifications`* (`poll_audio`) → OBC audio suite as
  `audio.clawcam:{node}` streams (a glassbreak becomes a safing-classifiable alarm).

**React:** OBC authors vision-driven reflex rules (verified alert subject → escalate
through Track 0) and foresight rules (rising sighting rate → escalate early).

**Act (OBC → ClawCam):** an OBC reflex sink translates `clawcam/cmd/*` actions into
ClawCam's gated write tools — `capture_now`, `set_device_state`, `create_alert_rule`
— over the same MCP bridge, still passing ClawCam's approval model. **No ClawCam-side
change was required**; these are exactly the tools the catalog SSOT already exposes.

**Implication for ClawCam:** the tool catalog and approval model are now load-bearing
for *closed-loop* control, not just operator reads. Keep `capture_now` /
`set_device_state` / `create_alert_rule` argument shapes stable, or bump the catalog
version and let the drift-guard + OBC `map_command` mapping catch it.

---

## Verification status

- **OBC (Rust):** approval scopes + plan-mode + funnel green on the maintainer's
  machine (16 approval unit tests; eval + doc-tests green).
- **ClawCam (Python):** plan-mode logic (`ArgumentBound` / `PlanStep` /
  `ApprovedPlan`) unit-verified; tool-catalog SSOT + gateway suites green;
  adapter plan-mode integration tests in `tests/gateway/test_phase13_plan_mode.py`.
  Run locally: `python -m pytest tests/gateway -q` (requires `croniter`,
  `python-multipart`).
