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
