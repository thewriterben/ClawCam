"""Schedule action type vocabulary."""

from __future__ import annotations


ACTION_SET_STATE = "set_state"
ACTION_SET_DEPLOYMENT_STATE = "set_deployment_state"
ACTION_ENABLE_RULE = "enable_rule"
ACTION_DISABLE_RULE = "disable_rule"
ACTION_WEBHOOK = "webhook"

ACTION_TYPES: tuple[str, ...] = (
    ACTION_SET_STATE,
    ACTION_SET_DEPLOYMENT_STATE,
    ACTION_ENABLE_RULE,
    ACTION_DISABLE_RULE,
    ACTION_WEBHOOK,
)


def is_valid_action(value: str | None) -> bool:
    return value in ACTION_TYPES
