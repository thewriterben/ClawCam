"""ClawCam gateway MQTT bridge.

Runs in a background thread. Connects to an MQTT broker (e.g., local Mosquitto),
subscribes to node event/health/ack topics, writes to the gateway SQLite database
via the same validation path as the HTTP REST API, and publishes commands to node
command topics immediately when they are queued.

Thread model:
  - paho-mqtt's network loop runs in a dedicated daemon thread.
  - The bridge exposes a thread-safe `publish_command()` method callable from
    any FastAPI request handler or tool function.
  - DB writes happen in the paho callback thread — GatewayDatabase uses short-lived
    SQLite connections so this is safe.

Broker requirements:
  - Any MQTT 3.1.1-compatible broker (Mosquitto, EMQX, HiveMQ).
  - No auth by default; configure broker_username/broker_password if needed.
  - Default port 1883 (unencrypted); set broker_tls=True for 8883.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

log = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    _PAHO_AVAILABLE = True
except ImportError:
    _PAHO_AVAILABLE = False
    mqtt = None  # type: ignore[assignment]

from .topics import (
    MQTT_ROOT,
    ack_topic,
    commands_topic,
    device_id_from_topic,
    events_topic,
    health_topic,
    topic_type,
)


class MQTTBridge:
    """Thread-safe MQTT ↔ SQLite bridge for the ClawCam gateway.

    Parameters
    ----------
    db:
        GatewayDatabase instance (duck-typed to avoid circular import).
    broker_host:
        Broker hostname or IP.
    broker_port:
        Broker port (default 1883).
    client_id:
        MQTT client identifier (default: "clawcam-gateway").
    mqtt_root:
        Topic root prefix (default: "clawcam").
    username / password:
        Optional broker credentials.
    """

    def __init__(
        self,
        db,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        client_id: str = "clawcam-gateway",
        mqtt_root: str = MQTT_ROOT,
        username: str | None = None,
        password: str | None = None,
    ):
        self._db = db
        self._host = broker_host
        self._port = broker_port
        self._root = mqtt_root
        self._client_id = client_id
        self._username = username
        self._password = password
        self._client = None
        self._connected = threading.Event()
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        return _PAHO_AVAILABLE

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        """Connect to the broker and start the network loop thread."""
        if not _PAHO_AVAILABLE:
            log.warning("paho-mqtt not installed; MQTT bridge disabled. "
                        "Install with: pip install paho-mqtt")
            return

        self._running = True
        self._client = mqtt.Client(client_id=self._client_id, protocol=mqtt.MQTTv311)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        if self._username:
            self._client.username_pw_set(self._username, self._password)

        try:
            self._client.connect(self._host, self._port, keepalive=60)
        except OSError as exc:
            log.error("MQTT bridge: could not connect to %s:%d — %s",
                      self._host, self._port, exc)
            self._running = False
            return

        self._client.loop_start()
        log.info("MQTT bridge: connecting to %s:%d", self._host, self._port)

    def stop(self) -> None:
        """Disconnect cleanly and stop the network loop."""
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected.clear()
        log.info("MQTT bridge: stopped")

    def publish_command(self, device_id: str, command: dict[str, Any]) -> bool:
        """Publish a command to the node's commands topic.

        Called from tool functions immediately after a command is queued in the DB,
        so nodes that are currently connected receive it without waiting for the
        next poll cycle.

        Returns True if the message was queued for delivery, False otherwise.
        """
        if not self._client or not self._connected.is_set():
            log.debug("MQTT bridge: not connected; command %s will be polled by node",
                      command.get("command_id"))
            return False

        topic = commands_topic(device_id, self._root)
        payload = json.dumps(command, separators=(",", ":"))
        result = self._client.publish(topic, payload, qos=1)
        if result.rc == 0:
            log.info("MQTT bridge: published command %s to %s",
                     command.get("command_id"), topic)
            return True
        log.warning("MQTT bridge: publish failed rc=%d for command %s",
                    result.rc, command.get("command_id"))
        return False

    def wait_connected(self, timeout: float = 5.0) -> bool:
        """Block until connected or timeout. Useful in tests."""
        return self._connected.wait(timeout=timeout)

    # ── paho callbacks ────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            log.error("MQTT bridge: connection refused (rc=%d)", rc)
            return
        log.info("MQTT bridge: connected to %s:%d", self._host, self._port)
        self._connected.set()

        # Subscribe to all node inbound topics
        for wildcard in (
            f"{self._root}/+/events",
            f"{self._root}/+/health",
            f"{self._root}/+/ack",
        ):
            client.subscribe(wildcard, qos=1)
            log.debug("MQTT bridge: subscribed to %s", wildcard)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected.clear()
        if rc != 0 and self._running:
            log.warning("MQTT bridge: unexpected disconnect (rc=%d); paho will reconnect", rc)

    def _on_message(self, client, userdata, message) -> None:
        topic = message.topic
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            log.warning("MQTT bridge: bad payload on %s: %s", topic, exc)
            return

        device_id = device_id_from_topic(topic, self._root)
        msg_type = topic_type(topic, self._root)

        if device_id is None or msg_type is None:
            return

        try:
            if msg_type == "events":
                self._process_event(device_id, payload)
            elif msg_type == "health":
                self._process_health(device_id, payload)
            elif msg_type == "ack":
                self._process_ack(device_id, payload)
        except Exception as exc:
            log.error("MQTT bridge: error processing %s from %s: %s", msg_type, device_id, exc)

    # ── DB write helpers ──────────────────────────────────────────────────────

    def _process_event(self, device_id: str, payload: dict[str, Any]) -> None:
        from clawcam_gateway.ingest.validation import validate_event
        if "device_id" not in payload:
            payload["device_id"] = device_id
        if "source" not in payload:
            payload["source"] = "mqtt"
        try:
            validate_event(payload)
        except Exception as exc:
            log.warning("MQTT bridge: invalid event from %s: %s", device_id, exc)
            return
        if self._db.get_device(device_id) is None:
            log.warning("MQTT bridge: unknown device %s; event dropped", device_id)
            return
        self._db.add_event(payload)
        log.info("MQTT bridge: stored event %s from %s", payload.get("event_id"), device_id)

    def _process_health(self, device_id: str, payload: dict[str, Any]) -> None:
        from clawcam_gateway.ingest.validation import validate_health
        if "device_id" not in payload:
            payload["device_id"] = device_id
        try:
            validate_health(payload)
        except Exception as exc:
            log.warning("MQTT bridge: invalid health from %s: %s", device_id, exc)
            return
        if self._db.get_device(device_id) is None:
            log.warning("MQTT bridge: unknown device %s; health record dropped", device_id)
            return
        self._db.add_health(payload)
        log.info("MQTT bridge: stored health from %s", device_id)

    def _process_ack(self, device_id: str, payload: dict[str, Any]) -> None:
        command_id = payload.get("command_id")
        status = payload.get("status")
        result = payload.get("result", {})
        if not command_id or status not in {"executed", "failed", "skipped"}:
            log.warning("MQTT bridge: invalid ack from %s: %s", device_id, payload)
            return
        updated = self._db.update_command_status(command_id, status, result=result)
        if updated:
            log.info("MQTT bridge: ack command %s as %s from %s", command_id, status, device_id)
        else:
            log.warning("MQTT bridge: unknown command_id %s in ack from %s", command_id, device_id)
