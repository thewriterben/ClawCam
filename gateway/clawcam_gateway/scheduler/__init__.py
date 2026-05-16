"""Cron-style schedule engine for ClawCam gateway.

Schedules are persistent rules that fire actions at specified times:
  - ``set_state``:           change a device's runtime state
  - ``set_deployment_state``: change a deployment's runtime state
  - ``enable_rule`` /
    ``disable_rule``:         toggle an alert rule
  - ``webhook``:              POST a JSON body to an arbitrary URL

Typical use cases:
  - "Arm the house at 10 PM weekdays, disarm at 7 AM": two schedules
    setting the deployment state via cron expressions.
  - "Only run BirdNET 5-9 AM and 4-8 PM": a pair of schedules toggling
    a per-rule ``enabled`` flag.
  - "Vacation mode for two weeks": a single schedule with starts_at and
    ends_at, no recurring cron, action=set_deployment_state.

The engine uses ``croniter`` for cron parsing and ships a synchronous
``tick(now)`` method that processes one wake cycle. The background loop
calls ``tick`` every 30 seconds; tests drive the same method directly
with mock timestamps so they don't depend on wall-clock progression.
"""

from clawcam_gateway.scheduler.engine import ScheduleEngine, ScheduleRunResult
from clawcam_gateway.scheduler.actions import (
    ACTION_DISABLE_RULE,
    ACTION_ENABLE_RULE,
    ACTION_SET_DEPLOYMENT_STATE,
    ACTION_SET_STATE,
    ACTION_TYPES,
    ACTION_WEBHOOK,
    is_valid_action,
)

__all__ = [
    "ScheduleEngine",
    "ScheduleRunResult",
    "ACTION_DISABLE_RULE",
    "ACTION_ENABLE_RULE",
    "ACTION_SET_DEPLOYMENT_STATE",
    "ACTION_SET_STATE",
    "ACTION_TYPES",
    "ACTION_WEBHOOK",
    "is_valid_action",
]
