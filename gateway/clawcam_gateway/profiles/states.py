"""Runtime state vocabulary for ClawCam devices and deployments.

States are deliberately stored as free-form strings rather than enforced
by a finite state machine. Real deployments need flexibility — a security
camera might briefly go from ``armed`` to ``maintenance`` to
``feeding`` (yes, the bird feeder one) if an operator switches it to a
different role for a few hours. The audit table ``state_transitions``
records every transition so the history is recoverable even when the
sequence makes no sense in theory.

Alert rules and the schedule engine consume these strings (e.g.
``required_state: armed``); they're values, not behavior.
"""

from __future__ import annotations


STATE_NORMAL = "normal"
STATE_ARMED = "armed"
STATE_DISARMED = "disarmed"
STATE_AWAY = "away"
STATE_VACATION = "vacation"
STATE_FEEDING = "feeding"
STATE_MAINTENANCE = "maintenance"

STATES: tuple[str, ...] = (
    STATE_NORMAL,
    STATE_ARMED,
    STATE_DISARMED,
    STATE_AWAY,
    STATE_VACATION,
    STATE_FEEDING,
    STATE_MAINTENANCE,
)

DEFAULT_STATE = STATE_NORMAL


def is_valid_state(value: str | None) -> bool:
    return value in STATES
