"""ClawCam MQTT topic conventions.

All topics are namespaced under a configurable root (default: "clawcam").

Node-to-gateway (publish):
  clawcam/{device_id}/events   — captured event JSON
  clawcam/{device_id}/health   — health/battery report JSON
  clawcam/{device_id}/ack      — command ack JSON {command_id, status, result}

Gateway-to-node (subscribe):
  clawcam/{device_id}/commands — command JSON (same shape as DB pending_commands)

Wildcard subscriptions the bridge uses:
  clawcam/+/events
  clawcam/+/health
  clawcam/+/ack
"""
from __future__ import annotations

MQTT_ROOT = "clawcam"


def events_topic(device_id: str, root: str = MQTT_ROOT) -> str:
    return f"{root}/{device_id}/events"


def health_topic(device_id: str, root: str = MQTT_ROOT) -> str:
    return f"{root}/{device_id}/health"


def ack_topic(device_id: str, root: str = MQTT_ROOT) -> str:
    return f"{root}/{device_id}/ack"


def commands_topic(device_id: str, root: str = MQTT_ROOT) -> str:
    return f"{root}/{device_id}/commands"


def device_id_from_topic(topic: str, root: str = MQTT_ROOT) -> str | None:
    """Extract device_id from any clawcam/{device_id}/... topic."""
    parts = topic.split("/")
    if len(parts) >= 3 and parts[0] == root:
        return parts[1]
    return None


def topic_type(topic: str, root: str = MQTT_ROOT) -> str | None:
    """Return the message type suffix ('events', 'health', 'ack', 'commands')."""
    parts = topic.split("/")
    if len(parts) >= 3 and parts[0] == root:
        return parts[2]
    return None
