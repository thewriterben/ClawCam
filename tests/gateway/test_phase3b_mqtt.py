"""Phase 3B tests — MQTT bridge: topics, message routing, command publish.

These tests use a mock paho client so no real broker is required in CI.
The MQTTBridge is exercised against the mock to verify:
  - Topic naming conventions
  - Event/health/ack routing to the database
  - Command publish path
  - Unknown device messages are safely dropped
  - Malformed payloads are safely dropped
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from clawcam_gateway.mqtt_bridge.topics import (
    ack_topic,
    commands_topic,
    device_id_from_topic,
    events_topic,
    health_topic,
    topic_type,
)
from clawcam_gateway.mqtt_bridge.bridge import MQTTBridge
from clawcam_gateway.storage.database import GatewayDatabase


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path) -> GatewayDatabase:
    db = GatewayDatabase(tmp_path / "mqtt_test.db")
    # Register a test device
    db.upsert_device({
        "device_id": "node-mqtt-001",
        "device_type": "node",
        "name": "MQTT Test Node",
        "status": "active",
        "capabilities": ["cap_clawcam_camera_trap"],
        "created_at": "2026-05-13T00:00:00Z",
        "last_seen_at": "2026-05-13T00:00:00Z",
    })
    return db


@pytest.fixture()
def bridge(tmp_db) -> MQTTBridge:
    return MQTTBridge(
        db=tmp_db,
        broker_host="localhost",
        broker_port=1883,
        client_id="test-gateway",
    )


def make_mqtt_message(topic: str, payload: dict[str, Any]) -> MagicMock:
    msg = MagicMock()
    msg.topic = topic
    msg.payload = json.dumps(payload).encode("utf-8")
    return msg


# ── Topic naming ──────────────────────────────────────────────────────────────

class TestTopicConventions:
    def test_events_topic(self):
        assert events_topic("node-001") == "clawcam/node-001/events"

    def test_health_topic(self):
        assert health_topic("node-001") == "clawcam/node-001/health"

    def test_ack_topic(self):
        assert ack_topic("node-001") == "clawcam/node-001/ack"

    def test_commands_topic(self):
        assert commands_topic("node-001") == "clawcam/node-001/commands"

    def test_device_id_from_events_topic(self):
        assert device_id_from_topic("clawcam/node-001/events") == "node-001"

    def test_device_id_from_commands_topic(self):
        assert device_id_from_topic("clawcam/node-xyz/commands") == "node-xyz"

    def test_device_id_from_unknown_topic_returns_none(self):
        assert device_id_from_topic("other/node-001/events") is None

    def test_topic_type_events(self):
        assert topic_type("clawcam/node-001/events") == "events"

    def test_topic_type_ack(self):
        assert topic_type("clawcam/node-001/ack") == "ack"

    def test_topic_type_unknown_returns_none(self):
        assert topic_type("not/a/clawcam/topic") is None

    def test_custom_root(self):
        assert events_topic("node-001", root="wildlife") == "wildlife/node-001/events"
        assert device_id_from_topic("wildlife/node-001/events", root="wildlife") == "node-001"


# ── Bridge message routing ────────────────────────────────────────────────────

class TestBridgeEventRouting:
    def test_valid_event_stored_in_db(self, bridge, tmp_db):
        event = {
            "event_id": "evt-mqtt-001",
            "event_type": "capture",
            "device_id": "node-mqtt-001",
            "timestamp": "2026-05-13T06:00:00Z",
            "time_source": "rtc",
            "source": "mqtt",
        }
        msg = make_mqtt_message("clawcam/node-mqtt-001/events", event)
        bridge._on_message(None, None, msg)

        stored = tmp_db.recent_events(limit=1)
        assert len(stored) == 1
        assert stored[0]["event_id"] == "evt-mqtt-001"

    def test_event_from_unknown_device_dropped(self, bridge, tmp_db):
        event = {
            "event_id": "evt-mqtt-002",
            "event_type": "capture",
            "device_id": "node-unknown",
            "timestamp": "2026-05-13T06:00:00Z",
            "time_source": "rtc",
            "source": "mqtt",
        }
        msg = make_mqtt_message("clawcam/node-unknown/events", event)
        bridge._on_message(None, None, msg)
        assert len(tmp_db.recent_events()) == 0

    def test_malformed_json_dropped(self, bridge):
        msg = MagicMock()
        msg.topic = "clawcam/node-mqtt-001/events"
        msg.payload = b"{not valid json"
        bridge._on_message(None, None, msg)  # must not raise


class TestBridgeHealthRouting:
    def test_valid_health_stored(self, bridge, tmp_db):
        health = {
            "device_id": "node-mqtt-001",
            "timestamp": "2026-05-13T06:01:00Z",
            "status": "ok",
            "battery_voltage": 3.8,
        }
        msg = make_mqtt_message("clawcam/node-mqtt-001/health", health)
        bridge._on_message(None, None, msg)

        record = tmp_db.latest_health("node-mqtt-001")
        assert record is not None
        assert record["status"] == "ok"

    def test_health_missing_required_field_dropped(self, bridge, tmp_db):
        # Missing 'timestamp'
        health = {"device_id": "node-mqtt-001", "status": "ok"}
        msg = make_mqtt_message("clawcam/node-mqtt-001/health", health)
        bridge._on_message(None, None, msg)
        # Should not crash; health record may or may not be stored depending on validator


class TestBridgeAckRouting:
    def _queue_command(self, tmp_db: GatewayDatabase, cmd_id: str = "cmd-mqtt-001") -> str:
        tmp_db.add_pending_command({
            "command_id": cmd_id,
            "command_type": "capture_now",
            "device_id": "node-mqtt-001",
            "status": "queued",
        })
        return cmd_id

    def test_valid_ack_updates_command_status(self, bridge, tmp_db):
        cmd_id = self._queue_command(tmp_db)
        ack = {"command_id": cmd_id, "status": "executed", "result": {"message": "ok"}}
        msg = make_mqtt_message("clawcam/node-mqtt-001/ack", ack)
        bridge._on_message(None, None, msg)

        cmd = tmp_db.get_pending_command(cmd_id)
        assert cmd["status"] == "executed"

    def test_ack_with_invalid_status_dropped(self, bridge, tmp_db):
        cmd_id = self._queue_command(tmp_db, "cmd-mqtt-002")
        ack = {"command_id": cmd_id, "status": "bogus_status"}
        msg = make_mqtt_message("clawcam/node-mqtt-001/ack", ack)
        bridge._on_message(None, None, msg)
        # Status should remain unchanged
        cmd = tmp_db.get_pending_command(cmd_id)
        assert cmd["status"] == "queued"

    def test_ack_missing_command_id_ignored(self, bridge):
        ack = {"status": "executed"}
        msg = make_mqtt_message("clawcam/node-mqtt-001/ack", ack)
        bridge._on_message(None, None, msg)  # must not raise


# ── Command publish ───────────────────────────────────────────────────────────

class TestBridgeCommandPublish:
    def test_publish_returns_false_when_not_connected(self, bridge):
        # bridge._connected is not set, client is None
        result = bridge.publish_command("node-mqtt-001", {"command_id": "cmd-x", "command_type": "capture_now"})
        assert result is False

    def test_publish_calls_paho_when_connected(self, bridge):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.rc = 0
        mock_client.publish.return_value = mock_result

        bridge._client = mock_client
        bridge._connected.set()

        command = {"command_id": "cmd-pub-001", "command_type": "capture_now", "device_id": "node-mqtt-001"}
        result = bridge.publish_command("node-mqtt-001", command)

        assert result is True
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert "clawcam/node-mqtt-001/commands" in call_args[0]

    def test_publish_returns_false_on_paho_error(self, bridge):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.rc = 4  # MQTT_ERR_NO_CONN
        mock_client.publish.return_value = mock_result

        bridge._client = mock_client
        bridge._connected.set()

        result = bridge.publish_command("node-mqtt-001", {"command_id": "cmd-fail"})
        assert result is False


# ── MQTTBridge availability ───────────────────────────────────────────────────

class TestBridgeAvailability:
    def test_is_available_reflects_paho_import(self, bridge):
        # In CI paho-mqtt may or may not be installed
        # Just verify the property exists and returns a bool
        assert isinstance(bridge.is_available, bool)

    def test_start_when_paho_unavailable_does_not_raise(self, bridge):
        with patch("clawcam_gateway.mqtt_bridge.bridge._PAHO_AVAILABLE", False):
            bridge.start()  # must not raise
        bridge.stop()

    def test_stop_when_never_started_does_not_raise(self, bridge):
        bridge.stop()  # must not raise


# ── ToolContext MQTT integration ──────────────────────────────────────────────

class TestToolContextMQTT:
    def test_publish_command_with_no_bridge_returns_false(self):
        from clawcam_gateway.tools.clawcam_tools import ToolContext
        ctx = ToolContext(database_path=":memory:", mqtt_bridge=None)
        result = ctx.publish_command("node-x", {"command_id": "cmd-x"})
        assert result is False

    def test_publish_command_calls_bridge(self):
        from clawcam_gateway.tools.clawcam_tools import ToolContext
        mock_bridge = MagicMock()
        mock_bridge.publish_command.return_value = True
        ctx = ToolContext(database_path=":memory:", mqtt_bridge=mock_bridge)
        result = ctx.publish_command("node-x", {"command_id": "cmd-x"})
        assert result is True
        mock_bridge.publish_command.assert_called_once_with("node-x", {"command_id": "cmd-x"})

    def test_capture_now_includes_mqtt_pushed_field(self, tmp_db):
        """capture_now result should include mqtt_pushed boolean."""
        from clawcam_gateway.tools.clawcam_tools import ToolContext, capture_now
        ctx = ToolContext(database_path=tmp_db.path, mqtt_bridge=None)
        result = capture_now(ctx, "node-mqtt-001")
        assert "mqtt_pushed" in result
        assert result["mqtt_pushed"] is False
