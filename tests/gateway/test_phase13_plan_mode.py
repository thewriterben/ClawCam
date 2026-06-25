"""Phase 13 (WS6): plan-mode approval tests for the brain adapter.

Plan-mode is the lockstep counterpart to Oh-Ben-Claw's ``ApprovedPlan``
(``src/approval/mod.rs``): a plan is approved once — tools plus per-argument
bounds — then execution is checked step by step, and the first violation
revokes the whole plan (halt on drift).

The pure-unit half mirrors OBC's Rust unit tests; the integration half drives a
real stdio-bridge subprocess exactly like ``test_phase13_approvals.py``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clawcam_gateway.ingest.cli import import_directory
from clawcam_gateway.simulator.node_simulator import SimulatedNode
from clawcam_gateway.storage.database import GatewayDatabase

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_DIR = REPO_ROOT / "brain" / "oh-ben-claw-adapter"
GATEWAY_DIR = REPO_ROOT / "gateway"

sys.path.insert(0, str(ADAPTER_DIR))

from clawcam_adapter import (  # noqa: E402
    VIOLATION_ARG_OUT_OF_BOUNDS,
    VIOLATION_PLAN_EXHAUSTED,
    VIOLATION_UNKNOWN_PLAN,
    VIOLATION_UNLISTED_ARG,
    VIOLATION_WRONG_TOOL,
    ApprovalRequired,
    ApprovedPlan,
    ArgumentBound,
    ClawCamAdapter,
    PlanStep,
    PlanViolationError,
)


# ── ArgumentBound ──────────────────────────────────────────────────────────


def test_bound_exact_matches_only_equal_value() -> None:
    b = ArgumentBound.exact("node-1")
    assert b.allows("node-1")
    assert not b.allows("node-2")


def test_bound_one_of_membership() -> None:
    b = ArgumentBound.one_of(["a", "b"])
    assert b.allows("a") and b.allows("b")
    assert not b.allows("c")


def test_bound_range_inclusive_and_rejects_non_numbers() -> None:
    b = ArgumentBound.range(0, 10)
    assert b.allows(0) and b.allows(10) and b.allows(5.5)
    assert not b.allows(-1) and not b.allows(11)
    assert not b.allows("5")  # strings are not numbers
    assert not b.allows(True)  # bools are not numbers (mirror OBC as_f64)


def test_bound_any_accepts_everything() -> None:
    b = ArgumentBound.any()
    assert b.allows(123) and b.allows("x") and b.allows(None)


def test_bound_from_dict_is_wire_compatible_with_obc_serde() -> None:
    # The tagged shapes Oh-Ben-Claw's serde emits must parse identically here.
    assert ArgumentBound.from_dict({"kind": "exact", "value": 7}).allows(7)
    assert ArgumentBound.from_dict({"kind": "one_of", "values": [1, 2]}).allows(2)
    assert ArgumentBound.from_dict({"kind": "range", "min": 1.0, "max": 4.0}).allows(3)
    assert ArgumentBound.from_dict({"kind": "any"}).allows("anything")
    with pytest.raises(ValueError):
        ArgumentBound.from_dict({"kind": "bogus"})


# ── ApprovedPlan.check_next ────────────────────────────────────────────────


def _plan(*steps: PlanStep) -> ApprovedPlan:
    return ApprovedPlan(plan_id="p", steps=list(steps), created_at="t")


def test_check_next_happy_path_advances_cursor() -> None:
    plan = _plan(
        PlanStep("capture_now", {"device_id": ArgumentBound.exact("node-1")}),
        PlanStep("create_alert_rule", {}),
    )
    plan.check_next("capture_now", {"device_id": "node-1"})
    assert plan.cursor == 1 and not plan.is_complete()
    plan.check_next("create_alert_rule", {"name": "x"})
    assert plan.cursor == 2 and plan.is_complete()


def test_check_next_wrong_tool() -> None:
    plan = _plan(PlanStep("capture_now"))
    with pytest.raises(PlanViolationError) as exc:
        plan.check_next("queue_firmware_update", {})
    assert exc.value.kind == VIOLATION_WRONG_TOOL


def test_check_next_arg_out_of_bounds() -> None:
    plan = _plan(PlanStep("create_schedule", {"interval_s": ArgumentBound.range(1, 60)}))
    with pytest.raises(PlanViolationError) as exc:
        plan.check_next("create_schedule", {"interval_s": 999})
    assert exc.value.kind == VIOLATION_ARG_OUT_OF_BOUNDS
    assert exc.value.detail["key"] == "interval_s"


def test_bounded_but_absent_key_is_out_of_bounds_unless_any() -> None:
    plan = _plan(PlanStep("capture_now", {"device_id": ArgumentBound.exact("node-1")}))
    with pytest.raises(PlanViolationError) as exc:
        plan.check_next("capture_now", {})  # device_id missing
    assert exc.value.kind == VIOLATION_ARG_OUT_OF_BOUNDS

    # ...but an Any bound tolerates the key being absent.
    plan_any = _plan(PlanStep("capture_now", {"device_id": ArgumentBound.any()}))
    plan_any.check_next("capture_now", {})
    assert plan_any.is_complete()


def test_deny_unlisted_args() -> None:
    plan = _plan(
        PlanStep(
            "capture_now",
            {"device_id": ArgumentBound.exact("node-1")},
            deny_unlisted_args=True,
        )
    )
    with pytest.raises(PlanViolationError) as exc:
        plan.check_next("capture_now", {"device_id": "node-1", "extra": 1})
    assert exc.value.kind == VIOLATION_UNLISTED_ARG
    assert exc.value.detail["key"] == "extra"


def test_plan_exhausted() -> None:
    plan = _plan(PlanStep("capture_now"))
    plan.check_next("capture_now", {})
    with pytest.raises(PlanViolationError) as exc:
        plan.check_next("capture_now", {})
    assert exc.value.kind == VIOLATION_PLAN_EXHAUSTED


def test_plan_step_from_dict_round_trips_obc_shape() -> None:
    step = PlanStep.from_dict({
        "tool_name": "create_schedule",
        "bounds": {"interval_s": {"kind": "range", "min": 1, "max": 60}},
        "deny_unlisted_args": True,
    })
    assert step.tool_name == "create_schedule"
    assert step.deny_unlisted_args is True
    step.bounds["interval_s"].allows(30)


# ── Adapter plan registry (halt on drift) ──────────────────────────────────


def test_approve_plan_returns_id_and_tracks_active_count() -> None:
    adapter = ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path="unused.db")
    pid = adapter.approve_plan([PlanStep("capture_now")])
    assert isinstance(pid, str) and adapter.active_plan_count() == 1


def test_unknown_plan_id_raises_unknown_plan() -> None:
    adapter = ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path="unused.db")
    with pytest.raises(PlanViolationError) as exc:
        adapter.check_plan_call("nope", "capture_now", {})
    assert exc.value.kind == VIOLATION_UNKNOWN_PLAN


def test_violation_revokes_plan_halt_on_drift() -> None:
    adapter = ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path="unused.db")
    pid = adapter.approve_plan([PlanStep("capture_now"), PlanStep("create_alert_rule")])
    # Drift on step 1: wrong tool.
    with pytest.raises(PlanViolationError):
        adapter.check_plan_call(pid, "queue_firmware_update", {})
    assert adapter.active_plan_count() == 0
    # Plan is gone — even a correct next call now fails unknown_plan.
    with pytest.raises(PlanViolationError) as exc:
        adapter.check_plan_call(pid, "capture_now", {})
    assert exc.value.kind == VIOLATION_UNKNOWN_PLAN


# ── Integration through the real stdio bridge ──────────────────────────────


def _seed_gateway(tmp_path) -> Path:
    db_path = tmp_path / "gateway.db"
    bundle_dir = tmp_path / "bundle"
    SimulatedNode(device_id="node-ws6", name="Plan Camera").write_bundle(
        bundle_dir,
        datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
    )
    db = GatewayDatabase(db_path)
    import_directory(bundle_dir, db)
    return db_path


def _adapter(tmp_path) -> ClawCamAdapter:
    return ClawCamAdapter(gateway_dir=GATEWAY_DIR, db_path=_seed_gateway(tmp_path))


def test_plan_pre_authorizes_gated_call_without_approved_flag(tmp_path) -> None:
    with _adapter(tmp_path) as adapter:
        pid = adapter.approve_plan([
            PlanStep("capture_now", {"device_id": ArgumentBound.exact("node-ws6")})
        ])
        # No approved=True needed — the plan IS the approval.
        adapter.call_tool("capture_now", {"device_id": "node-ws6"}, plan_id=pid)
        funnel = adapter.funnel_summary()["capture_now"]
        assert funnel["approved_plan"] == 1
        assert funnel["denied"] == 0
        # Single-step plan is consumed on success.
        assert adapter.active_plan_count() == 0


def test_plan_violation_through_call_tool_revokes_and_audits(tmp_path) -> None:
    with _adapter(tmp_path) as adapter:
        pid = adapter.approve_plan([
            PlanStep("capture_now", {"device_id": ArgumentBound.exact("node-ws6")})
        ])
        # Wrong device_id violates the bound → revoke, no dispatch.
        with pytest.raises(PlanViolationError):
            adapter.call_tool("capture_now", {"device_id": "intruder"}, plan_id=pid)
        assert adapter.funnel_summary()["capture_now"]["plan_violation"] == 1
        assert adapter.active_plan_count() == 0
        # The revoked plan can no longer authorize anything.
        with pytest.raises(PlanViolationError):
            adapter.call_tool("capture_now", {"device_id": "node-ws6"}, plan_id=pid)
        # And without a plan or grant, the tool is still gated.
        with pytest.raises(ApprovalRequired):
            adapter.call_tool("capture_now", {"device_id": "node-ws6"})
