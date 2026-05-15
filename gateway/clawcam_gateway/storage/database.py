"""SQLite persistence for the ClawCam gateway."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterator


class GatewayDatabase:
    """Durable local database for offline-first ClawCam field gateways."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.parent and str(self.path.parent) != ".":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    device_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(device_id) REFERENCES devices(device_id)
                );

                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(event_id) REFERENCES events(event_id)
                );

                CREATE TABLE IF NOT EXISTS health_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(device_id) REFERENCES devices(device_id)
                );

                CREATE TABLE IF NOT EXISTS media (
                    media_id TEXT PRIMARY KEY,
                    event_id TEXT,
                    media_type TEXT NOT NULL,
                    path TEXT,
                    uri TEXT,
                    mime_type TEXT,
                    size_bytes INTEGER,
                    sha256 TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(event_id) REFERENCES events(event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_device_id ON events(device_id);
                CREATE INDEX IF NOT EXISTS idx_health_device_id ON health_records(device_id);

                CREATE TABLE IF NOT EXISTS pending_commands (
                    command_id TEXT PRIMARY KEY,
                    command_type TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_pending_commands_device ON pending_commands(device_id);
                CREATE INDEX IF NOT EXISTS idx_pending_commands_status ON pending_commands(status);

                CREATE TABLE IF NOT EXISTS inference_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    media_path TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    detections_json TEXT NOT NULL,
                    top_label TEXT,
                    top_confidence REAL,
                    top_species TEXT,
                    ran_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(event_id) REFERENCES events(event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_inference_event_id ON inference_results(event_id);
                CREATE INDEX IF NOT EXISTS idx_inference_top_label ON inference_results(top_label);
                CREATE INDEX IF NOT EXISTS idx_inference_ran_at ON inference_results(ran_at);

                CREATE TABLE IF NOT EXISTS firmware_builds (
                    build_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS cloud_uploads (
                    upload_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT,
                    media_path TEXT NOT NULL,
                    remote_uri TEXT,
                    provider TEXT NOT NULL DEFAULT 'noop',
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    queued_at TEXT NOT NULL DEFAULT (datetime('now')),
                    uploaded_at TEXT,
                    FOREIGN KEY(event_id) REFERENCES events(event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_cloud_uploads_event ON cloud_uploads(event_id);
                CREATE INDEX IF NOT EXISTS idx_cloud_uploads_status ON cloud_uploads(status);
                CREATE INDEX IF NOT EXISTS idx_cloud_uploads_queued ON cloud_uploads(queued_at);

                CREATE TABLE IF NOT EXISTS alert_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    label TEXT,
                    min_confidence REAL NOT NULL DEFAULT 0.5,
                    species_pattern TEXT,
                    device_id TEXT,
                    webhook_url TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON alert_rules(enabled);

                CREATE TABLE IF NOT EXISTS alert_events (
                    alert_event_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    rule_name TEXT NOT NULL,
                    event_id TEXT,
                    device_id TEXT,
                    top_label TEXT,
                    top_confidence REAL,
                    top_species TEXT,
                    webhook_url TEXT,
                    delivery_status TEXT NOT NULL DEFAULT 'pending',
                    webhook_response TEXT,
                    fired_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(rule_id) REFERENCES alert_rules(rule_id)
                );

                CREATE INDEX IF NOT EXISTS idx_alert_events_rule ON alert_events(rule_id);
                CREATE INDEX IF NOT EXISTS idx_alert_events_fired ON alert_events(fired_at);
                CREATE INDEX IF NOT EXISTS idx_alert_events_status ON alert_events(delivery_status);
                """
            )

    def upsert_device(self, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO devices (device_id, device_type, name, status, payload_json, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    device_type = excluded.device_type,
                    name = excluded.name,
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    payload["device_id"],
                    payload["device_type"],
                    payload["name"],
                    payload["status"],
                    json.dumps(payload, sort_keys=True),
                    payload["created_at"],
                    payload.get("last_seen_at"),
                ),
            )

    def add_event(self, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (event_id, event_type, device_id, timestamp, source, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["event_id"],
                    payload["event_type"],
                    payload["device_id"],
                    payload["timestamp"],
                    payload["source"],
                    json.dumps(payload, sort_keys=True),
                ),
            )
            for media in payload.get("media", []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO media
                    (media_id, event_id, media_type, path, uri, mime_type, size_bytes, sha256, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        media["media_id"],
                        payload["event_id"],
                        media["media_type"],
                        media.get("path"),
                        media.get("uri"),
                        media.get("mime_type"),
                        media.get("size_bytes"),
                        media.get("sha256"),
                        json.dumps(media, sort_keys=True),
                    ),
                )

    def add_health(self, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO health_records (device_id, timestamp, status, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    payload["device_id"],
                    payload["timestamp"],
                    payload["status"],
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def recent_events(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_devices(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM devices ORDER BY name ASC, device_id ASC"
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def add_pending_command(self, command: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_commands (command_id, command_type, device_id, status, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    command["command_id"],
                    command["command_type"],
                    command["device_id"],
                    command.get("status", "queued"),
                    json.dumps(command, sort_keys=True),
                ),
            )

    def get_pending_command(self, command_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM pending_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_pending_commands(self, device_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if device_id and status:
                rows = conn.execute(
                    "SELECT payload_json FROM pending_commands WHERE device_id = ? AND status = ? ORDER BY created_at DESC",
                    (device_id, status),
                ).fetchall()
            elif device_id:
                rows = conn.execute(
                    "SELECT payload_json FROM pending_commands WHERE device_id = ? ORDER BY created_at DESC",
                    (device_id,),
                ).fetchall()
            elif status:
                rows = conn.execute(
                    "SELECT payload_json FROM pending_commands WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload_json FROM pending_commands ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def update_command_status(self, command_id: str, status: str, result: dict[str, Any] | None = None) -> bool:
        with self.connect() as conn:
            if result is not None:
                existing = conn.execute(
                    "SELECT payload_json FROM pending_commands WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                if existing:
                    payload = json.loads(existing["payload_json"])
                    payload["status"] = status
                    payload["result"] = result
                    cursor = conn.execute(
                        "UPDATE pending_commands SET status = ?, payload_json = ?, updated_at = datetime('now') WHERE command_id = ?",
                        (status, json.dumps(payload, sort_keys=True), command_id),
                    )
                else:
                    return False
            else:
                cursor = conn.execute(
                    "UPDATE pending_commands SET status = ?, updated_at = datetime('now') WHERE command_id = ?",
                    (status, command_id),
                )
        return cursor.rowcount > 0

    def get_device_capabilities(self, device_id: str) -> list[str]:
        device = self.get_device(device_id)
        if device is None:
            return []
        return device.get("capabilities", [])

    def save_inference_result(self, event_id: str, media_path: str, result: Any) -> None:
        """Persist an InferenceResult (duck-typed) for an event."""
        d = result.to_dict()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO inference_results
                    (event_id, media_path, model_name, model_version,
                     detections_json, top_label, top_confidence, top_species)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    media_path,
                    d["model_name"],
                    d["model_version"],
                    json.dumps(d["detections"], sort_keys=True),
                    d.get("top_label"),
                    d.get("top_confidence"),
                    d.get("top_species"),
                ),
            )

    def get_inference_result(self, event_id: str) -> dict[str, Any] | None:
        """Return the most recent inference result for an event, or None."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT event_id, media_path, model_name, model_version,
                       detections_json, top_label, top_confidence, top_species, ran_at
                FROM inference_results
                WHERE event_id = ?
                ORDER BY ran_at DESC
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "event_id": row["event_id"],
            "media_path": row["media_path"],
            "model_name": row["model_name"],
            "model_version": row["model_version"],
            "detections": json.loads(row["detections_json"]),
            "top_label": row["top_label"],
            "top_confidence": row["top_confidence"],
            "top_species": row["top_species"],
            "ran_at": row["ran_at"],
        }

    def list_inference_results(
        self,
        limit: int = 25,
        label: str | None = None,
        min_confidence: float = 0.0,
        species: str | None = None,
    ) -> list[dict[str, Any]]:
        """List recent inference results with optional filtering."""
        clauses = ["top_confidence >= ?"]
        params: list[Any] = [min_confidence]
        if label:
            clauses.append("top_label = ?")
            params.append(label)
        if species:
            clauses.append("top_species LIKE ?")
            params.append(f"%{species}%")
        where = " AND ".join(clauses)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT event_id, media_path, model_name, model_version,
                       detections_json, top_label, top_confidence, top_species, ran_at
                FROM inference_results
                WHERE {where}
                ORDER BY ran_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "media_path": row["media_path"],
                "model_name": row["model_name"],
                "model_version": row["model_version"],
                "detections": json.loads(row["detections_json"]),
                "top_label": row["top_label"],
                "top_confidence": row["top_confidence"],
                "top_species": row["top_species"],
                "ran_at": row["ran_at"],
            }
            for row in rows
        ]

    def add_firmware_build(
        self, build_id: str, version: str, filename: str, sha256: str, size_bytes: int
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO firmware_builds (build_id, version, filename, sha256, size_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (build_id, version, filename, sha256, size_bytes),
            )

    def get_firmware_build(self, build_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM firmware_builds WHERE build_id = ?", (build_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_firmware_builds(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM firmware_builds ORDER BY uploaded_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_cloud_upload(
        self,
        event_id: str | None,
        media_path: str,
        provider: str = "noop",
    ) -> int:
        """Insert a cloud_uploads row with status='pending'. Returns upload_id."""
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_uploads (event_id, media_path, provider, status)
                VALUES (?, ?, ?, 'pending')
                """,
                (event_id, media_path, provider),
            )
        return cursor.lastrowid  # type: ignore[return-value]

    def update_cloud_upload(
        self,
        upload_id: int,
        status: str,
        remote_uri: str | None = None,
        error: str | None = None,
        uploaded_at: str | None = None,
    ) -> None:
        """Update status and optional fields for a cloud_uploads row."""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE cloud_uploads
                SET status = ?, remote_uri = ?, error = ?, uploaded_at = ?
                WHERE upload_id = ?
                """,
                (status, remote_uri, error, uploaded_at, upload_id),
            )

    def list_cloud_uploads(
        self,
        limit: int = 25,
        status: str | None = None,
        event_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent cloud upload records with optional filtering."""
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT upload_id, event_id, media_path, remote_uri, provider,
                       status, error, queued_at, uploaded_at
                FROM cloud_uploads
                {where}
                ORDER BY queued_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_cloud_upload_summary(self) -> dict[str, int]:
        """Return counts grouped by status: {pending: N, uploaded: N, failed: N}."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM cloud_uploads GROUP BY status"
            ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    # ── Alert rules ───────────────────────────────────────────────────────

    def add_alert_rule(self, rule: dict[str, Any]) -> None:
        """Insert a new alert rule row."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_rules
                    (rule_id, name, label, min_confidence, species_pattern,
                     device_id, webhook_url, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["rule_id"],
                    rule["name"],
                    rule.get("label"),
                    float(rule.get("min_confidence", 0.5)),
                    rule.get("species_pattern"),
                    rule.get("device_id"),
                    rule.get("webhook_url"),
                    1 if rule.get("enabled", True) else 0,
                ),
            )

    def get_alert_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Return a single alert rule by rule_id, or None."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT rule_id, name, label, min_confidence, species_pattern,
                       device_id, webhook_url, enabled, created_at
                FROM alert_rules WHERE rule_id = ?
                """,
                (rule_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return d

    def list_alert_rules(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return all alert rules, optionally filtering to enabled ones."""
        where = "WHERE enabled = 1" if enabled_only else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT rule_id, name, label, min_confidence, species_pattern,
                       device_id, webhook_url, enabled, created_at
                FROM alert_rules {where}
                ORDER BY created_at DESC
                """
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["enabled"] = bool(d["enabled"])
            result.append(d)
        return result

    def update_alert_rule(self, rule_id: str, updates: dict[str, Any]) -> bool:
        """Apply *updates* dict to an existing alert rule. Returns True if found."""
        allowed = {"name", "label", "min_confidence", "species_pattern",
                   "device_id", "webhook_url", "enabled"}
        sets = []
        params: list[Any] = []
        for key, val in updates.items():
            if key not in allowed:
                continue
            if key == "enabled":
                val = 1 if val else 0
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            return False
        params.append(rule_id)
        with self.connect() as conn:
            cur = conn.execute(
                f"UPDATE alert_rules SET {', '.join(sets)} WHERE rule_id = ?",
                params,
            )
        return cur.rowcount > 0

    def delete_alert_rule(self, rule_id: str) -> bool:
        """Delete an alert rule by rule_id. Returns True if a row was deleted."""
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM alert_rules WHERE rule_id = ?",
                (rule_id,),
            )
        return cur.rowcount > 0

    # ── Alert events ──────────────────────────────────────────────────────

    def add_alert_event(self, event: dict[str, Any]) -> None:
        """Persist a fired alert event row."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_events
                    (alert_event_id, rule_id, rule_name, event_id, device_id,
                     top_label, top_confidence, top_species, webhook_url,
                     delivery_status, webhook_response, fired_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["alert_event_id"],
                    event["rule_id"],
                    event["rule_name"],
                    event.get("event_id"),
                    event.get("device_id"),
                    event.get("top_label"),
                    event.get("top_confidence"),
                    event.get("top_species"),
                    event.get("webhook_url"),
                    event.get("delivery_status", "pending"),
                    event.get("webhook_response"),
                    event.get("fired_at"),
                ),
            )

    def list_alert_events(
        self,
        limit: int = 25,
        rule_id: str | None = None,
        delivery_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent alert events with optional filtering."""
        clauses = []
        params: list[Any] = []
        if rule_id:
            clauses.append("rule_id = ?")
            params.append(rule_id)
        if delivery_status:
            clauses.append("delivery_status = ?")
            params.append(delivery_status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT alert_event_id, rule_id, rule_name, event_id, device_id,
                       top_label, top_confidence, top_species, webhook_url,
                       delivery_status, webhook_response, fired_at
                FROM alert_events
                {where}
                ORDER BY fired_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_health(self, device_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM health_records
                WHERE device_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None
