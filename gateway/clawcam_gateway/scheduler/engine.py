"""ScheduleEngine: evaluates schedules and fires actions when they're due.

Designed to be unit-testable: ``tick(now)`` is synchronous and idempotent
within a wake-window. The background thread in ``start()`` just calls
``tick(now=datetime.now(timezone.utc))`` every 30 seconds. Tests pass
explicit ``now`` values to drive the engine without sleeping.

Schedule semantics
------------------
A schedule fires when **next_run_at <= now**. Stored fields:

  - ``cron_expr``: standard 5-field cron (UTC). Used to compute the next
    ``next_run_at`` after each fire. NULL = one-shot.
  - ``starts_at`` / ``ends_at``: ISO datetime gates. Outside this window
    the schedule is dormant. NULL means "no bound on that side".

Action dispatch
---------------
Each action_type maps to a handler that consumes the JSON payload.
Handlers return a ``ScheduleRunResult`` that goes into the audit log.
Handlers must never raise; they capture exceptions and report
``status="failed"`` with an error message.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from clawcam_gateway.scheduler.actions import (
    ACTION_DISABLE_RULE,
    ACTION_ENABLE_RULE,
    ACTION_SET_DEPLOYMENT_STATE,
    ACTION_SET_STATE,
    ACTION_WEBHOOK,
)

if TYPE_CHECKING:
    from clawcam_gateway.storage.database import GatewayDatabase

logger = logging.getLogger(__name__)


# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class ScheduleRunResult:
    """Per-fire outcome recorded in the ``schedule_runs`` audit table."""

    schedule_id: str
    status: str          # "success" | "failed" | "skipped"
    detail: dict[str, Any]
    error: str | None = None


# ── Cron helpers (lazy import so croniter remains optional in tests) ─────────


def _next_cron(expr: str, base: datetime) -> datetime:
    """Return the next datetime after *base* that matches the cron expression.

    Uses croniter; raises ValueError on an unparseable expression so the
    caller can surface a clear 400 error.
    """
    try:
        from croniter import croniter  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise RuntimeError("croniter is required for cron schedules; pip install croniter") from exc

    if not croniter.is_valid(expr):
        raise ValueError(f"invalid cron expression: {expr!r}")
    iterator = croniter(expr, base)
    return iterator.get_next(datetime)


# ── Engine ───────────────────────────────────────────────────────────────────


class ScheduleEngine:
    """Owns the schedule-evaluation loop and action dispatch.

    Args:
        db:                 GatewayDatabase instance (also the action target).
        webhook_deliverer:  Callable used for action=webhook; default is
                            ``deliver_webhook`` from the alerts package.
        tick_interval_s:    Wake-up cadence for the background loop.
    """

    def __init__(self, db: "GatewayDatabase", webhook_deliverer=None,
                 tick_interval_s: int = 30):
        self._db = db
        self._tick_interval = tick_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if webhook_deliverer is None:
            from clawcam_gateway.alerts.webhook import deliver_webhook
            webhook_deliverer = deliver_webhook
        self._deliver_webhook = webhook_deliverer

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ClawCamScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._tick_interval + 5)
            self._thread = None

    def _run(self) -> None:  # pragma: no cover - background loop tested via tick
        while not self._stop.wait(self._tick_interval):
            try:
                self.tick(datetime.now(timezone.utc))
            except Exception as exc:  # noqa: BLE001
                logger.warning("scheduler tick raised: %s", exc)

    # ── Synchronous tick ───────────────────────────────────────────────────

    def tick(self, now: datetime | None = None) -> list[ScheduleRunResult]:
        """Evaluate every enabled schedule against *now* and fire due ones.

        Returns a list of ``ScheduleRunResult`` for every schedule that
        fired (or was attempted) in this tick. Schedules outside their
        ``starts_at``/``ends_at`` window are silently skipped without
        returning a result.
        """
        now = now or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        results: list[ScheduleRunResult] = []

        for schedule in self._db.list_schedules(enabled_only=True):
            # Time-window gates
            starts_at = schedule.get("starts_at")
            ends_at = schedule.get("ends_at")
            if starts_at and now_iso < starts_at:
                continue
            if ends_at and now_iso > ends_at:
                continue

            next_run_at = schedule.get("next_run_at")
            if next_run_at and now_iso < next_run_at:
                continue
            # If no next_run_at recorded yet AND a cron expr is set, compute
            # the next fire based on now and skip THIS tick (don't fire
            # immediately on first sight).
            if next_run_at is None and schedule.get("cron_expr"):
                try:
                    upcoming = _next_cron(schedule["cron_expr"], now)
                    self._db.update_schedule_run_times(
                        schedule["schedule_id"], last_run_at=None,
                        next_run_at=upcoming.isoformat(),
                    )
                except ValueError:
                    pass
                continue

            # Fire it
            result = self._dispatch(schedule)
            results.append(result)

            # Audit + reschedule
            self._db.record_schedule_run(result)

            # Compute next_run_at if cron-based
            next_run_iso: str | None = None
            if schedule.get("cron_expr"):
                try:
                    next_run_iso = _next_cron(schedule["cron_expr"], now).isoformat()
                except ValueError:
                    next_run_iso = None
            self._db.update_schedule_run_times(
                schedule["schedule_id"], last_run_at=now_iso,
                next_run_at=next_run_iso,
            )
            # One-shot schedules with no cron get disabled after firing.
            if not schedule.get("cron_expr"):
                self._db.update_schedule(schedule["schedule_id"], {"enabled": False})

        return results

    # ── Manual trigger ─────────────────────────────────────────────────────

    def run_now(self, schedule_id: str) -> ScheduleRunResult:
        """Fire a schedule immediately regardless of its next_run_at."""
        schedule = self._db.get_schedule(schedule_id)
        if schedule is None:
            return ScheduleRunResult(
                schedule_id=schedule_id, status="failed",
                detail={}, error=f"unknown schedule_id: {schedule_id}",
            )
        result = self._dispatch(schedule)
        self._db.record_schedule_run(result)
        return result

    # ── Action dispatch ────────────────────────────────────────────────────

    def _dispatch(self, schedule: dict[str, Any]) -> ScheduleRunResult:
        action_type = schedule.get("action_type", "")
        payload = schedule.get("action_payload") or {}
        sched_id = schedule["schedule_id"]
        try:
            if action_type == ACTION_SET_STATE:
                return self._action_set_state(sched_id, payload)
            if action_type == ACTION_SET_DEPLOYMENT_STATE:
                return self._action_set_deployment_state(sched_id, payload)
            if action_type == ACTION_ENABLE_RULE:
                return self._action_toggle_rule(sched_id, payload, enabled=True)
            if action_type == ACTION_DISABLE_RULE:
                return self._action_toggle_rule(sched_id, payload, enabled=False)
            if action_type == ACTION_WEBHOOK:
                return self._action_webhook(sched_id, payload)
            return ScheduleRunResult(
                schedule_id=sched_id, status="failed", detail={},
                error=f"unknown action_type: {action_type}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("schedule %s action %s raised: %s", sched_id, action_type, exc)
            return ScheduleRunResult(
                schedule_id=sched_id, status="failed", detail={}, error=str(exc),
            )

    def _action_set_state(self, sched_id: str, payload: dict[str, Any]) -> ScheduleRunResult:
        device_id = payload.get("device_id")
        new_state = payload.get("state")
        if not device_id or not new_state:
            return ScheduleRunResult(
                sched_id, status="failed", detail=payload,
                error="set_state requires device_id and state",
            )
        ok, prev = self._db.set_device_state(
            device_id, new_state,
            transitioned_by=f"scheduler:{sched_id}",
            reason=payload.get("reason", "scheduled transition"),
        )
        if not ok:
            return ScheduleRunResult(sched_id, status="failed", detail=payload,
                                     error=f"unknown device: {device_id}")
        return ScheduleRunResult(sched_id, status="success",
                                 detail={**payload, "previous_state": prev})

    def _action_set_deployment_state(self, sched_id: str, payload: dict[str, Any]) -> ScheduleRunResult:
        deployment_id = payload.get("deployment_id", "default")
        new_state = payload.get("state")
        if not new_state:
            return ScheduleRunResult(sched_id, status="failed", detail=payload,
                                     error="set_deployment_state requires state")
        ok, prev = self._db.set_deployment_state(
            deployment_id, new_state,
            transitioned_by=f"scheduler:{sched_id}",
            reason=payload.get("reason", "scheduled transition"),
        )
        if not ok:
            return ScheduleRunResult(sched_id, status="failed", detail=payload,
                                     error=f"unknown deployment: {deployment_id}")
        return ScheduleRunResult(sched_id, status="success",
                                 detail={**payload, "previous_state": prev})

    def _action_toggle_rule(self, sched_id: str, payload: dict[str, Any],
                             enabled: bool) -> ScheduleRunResult:
        rule_id = payload.get("rule_id")
        if not rule_id:
            return ScheduleRunResult(sched_id, status="failed", detail=payload,
                                     error="rule_id required")
        ok = self._db.update_alert_rule(rule_id, {"enabled": enabled})
        if not ok:
            return ScheduleRunResult(sched_id, status="failed", detail=payload,
                                     error=f"unknown rule_id: {rule_id}")
        return ScheduleRunResult(sched_id, status="success",
                                 detail={**payload, "enabled": enabled})

    def _action_webhook(self, sched_id: str, payload: dict[str, Any]) -> ScheduleRunResult:
        url = payload.get("url")
        body = payload.get("body", {})
        if not url:
            return ScheduleRunResult(sched_id, status="failed", detail=payload,
                                     error="webhook action requires url")
        success, status_code, error = self._deliver_webhook(url, body)
        return ScheduleRunResult(
            sched_id,
            status="success" if success else "failed",
            detail={"url": url, "http_status": status_code},
            error=error,
        )
