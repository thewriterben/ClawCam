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

                -- Phase 7: tenancy + auth -----------------------------------
                CREATE TABLE IF NOT EXISTS deployments (
                    deployment_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    profile TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'active',
                    description TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    deployment_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    scope TEXT NOT NULL DEFAULT 'read',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_used_at TEXT,
                    expires_at TEXT,
                    FOREIGN KEY(deployment_id) REFERENCES deployments(deployment_id)
                );

                CREATE INDEX IF NOT EXISTS idx_api_keys_deployment ON api_keys(deployment_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);

                INSERT OR IGNORE INTO deployments (deployment_id, name, profile, description)
                VALUES ('default', 'Default deployment', 'general',
                        'Auto-created. Used when CLAWCAM_AUTH_ENABLED is unset or false.');

                -- Phase 8: device profiles + state transitions audit ---------
                CREATE TABLE IF NOT EXISTS state_transitions (
                    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_kind TEXT NOT NULL,        -- 'device' | 'deployment'
                    target_id TEXT NOT NULL,
                    deployment_id TEXT NOT NULL DEFAULT 'default',
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    transitioned_by TEXT,
                    reason TEXT,
                    transitioned_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_state_transitions_target
                    ON state_transitions(target_kind, target_id);
                CREATE INDEX IF NOT EXISTS idx_state_transitions_deployment
                    ON state_transitions(deployment_id);
                CREATE INDEX IF NOT EXISTS idx_state_transitions_at
                    ON state_transitions(transitioned_at);

                -- Phase 9: schedule engine ----------------------------------
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    deployment_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    cron_expr TEXT,
                    starts_at TEXT,
                    ends_at TEXT,
                    action_type TEXT NOT NULL,
                    action_payload_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_run_at TEXT,
                    next_run_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled);
                CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON schedules(next_run_at);
                CREATE INDEX IF NOT EXISTS idx_schedules_deployment ON schedules(deployment_id);

                CREATE TABLE IF NOT EXISTS schedule_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_id TEXT NOT NULL,
                    ran_at TEXT NOT NULL DEFAULT (datetime('now')),
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    FOREIGN KEY(schedule_id) REFERENCES schedules(schedule_id)
                );

                CREATE INDEX IF NOT EXISTS idx_schedule_runs_schedule
                    ON schedule_runs(schedule_id);
                CREATE INDEX IF NOT EXISTS idx_schedule_runs_at
                    ON schedule_runs(ran_at);
                """
            )
            # Idempotent column-additions for legacy tables. ADD COLUMN is the
            # only schema change SQLite supports without rewriting the table,
            # so we wrap each in a try/except — re-runs after the first one
            # added the column will safely no-op via OperationalError.
            self._add_column_if_missing(conn, "devices", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "events", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "pending_commands", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "inference_results", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "firmware_builds", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "cloud_uploads", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "alert_rules", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "alert_events", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "health_records", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")
            self._add_column_if_missing(conn, "media", "deployment_id", "TEXT NOT NULL DEFAULT 'default'")

            # Phase 8 columns
            self._add_column_if_missing(conn, "devices", "profile", "TEXT NOT NULL DEFAULT 'general'")
            self._add_column_if_missing(conn, "devices", "state", "TEXT NOT NULL DEFAULT 'normal'")
            self._add_column_if_missing(conn, "deployments", "state", "TEXT NOT NULL DEFAULT 'normal'")
            # Alert rules gain an optional state gate
            self._add_column_if_missing(conn, "alert_rules", "required_state", "TEXT")

    @staticmethod
    def _add_column_if_missing(conn, table: str, column: str, column_def: str) -> None:
        """SQLite has no IF NOT EXISTS for ALTER TABLE — emulate it."""
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")

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
                "SELECT * FROM firmware_builds ORDER BY uploaded_at DESC, rowid DESC"
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

    # ── Deployments (Phase 7) ─────────────────────────────────────────────

    def add_deployment(self, deployment: dict[str, Any]) -> None:
        """Insert a new deployment row."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO deployments
                    (deployment_id, name, profile, status, description, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    deployment["deployment_id"],
                    deployment["name"],
                    deployment.get("profile", "general"),
                    deployment.get("status", "active"),
                    deployment.get("description"),
                    json.dumps(deployment.get("metadata", {}), sort_keys=True),
                ),
            )

    def get_deployment(self, deployment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT deployment_id, name, profile, status, description,
                       created_at, metadata_json
                FROM deployments WHERE deployment_id = ?
                """,
                (deployment_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
        return d

    def list_deployments(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE status = ?" if status else ""
        params: tuple = (status,) if status else ()
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT deployment_id, name, profile, status, description,
                       created_at, metadata_json
                FROM deployments {where} ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
            result.append(d)
        return result

    def update_deployment(self, deployment_id: str, updates: dict[str, Any]) -> bool:
        allowed = {"name", "profile", "status", "description"}
        sets = []
        params: list[Any] = []
        for key, val in updates.items():
            if key in allowed:
                sets.append(f"{key} = ?")
                params.append(val)
        if "metadata" in updates:
            sets.append("metadata_json = ?")
            params.append(json.dumps(updates["metadata"], sort_keys=True))
        if not sets:
            return False
        params.append(deployment_id)
        with self.connect() as conn:
            cur = conn.execute(
                f"UPDATE deployments SET {', '.join(sets)} WHERE deployment_id = ?",
                params,
            )
        return cur.rowcount > 0

    def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a deployment. Refuses to delete the 'default' deployment."""
        if deployment_id == "default":
            return False
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM deployments WHERE deployment_id = ?",
                (deployment_id,),
            )
        return cur.rowcount > 0

    # ── API keys (Phase 7) ────────────────────────────────────────────────

    def add_api_key(self, key: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys
                    (key_id, deployment_id, name, key_hash, scope,
                     enabled, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key["key_id"],
                    key["deployment_id"],
                    key["name"],
                    key["key_hash"],
                    key.get("scope", "read"),
                    1 if key.get("enabled", True) else 0,
                    key.get("expires_at"),
                ),
            )

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        """Look up an api_key by its SHA256 hash. Used by the auth middleware."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT key_id, deployment_id, name, scope, enabled,
                       created_at, last_used_at, expires_at
                FROM api_keys WHERE key_hash = ?
                """,
                (key_hash,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return d

    def get_api_key(self, key_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT key_id, deployment_id, name, scope, enabled,
                       created_at, last_used_at, expires_at
                FROM api_keys WHERE key_id = ?
                """,
                (key_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        return d

    def list_api_keys(self, deployment_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE deployment_id = ?" if deployment_id else ""
        params: tuple = (deployment_id,) if deployment_id else ()
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT key_id, deployment_id, name, scope, enabled,
                       created_at, last_used_at, expires_at
                FROM api_keys {where} ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["enabled"] = bool(d["enabled"])
            result.append(d)
        return result

    def touch_api_key(self, key_id: str) -> None:
        """Update last_used_at for an api_key. Best-effort, never raises."""
        try:
            with self.connect() as conn:
                conn.execute(
                    "UPDATE api_keys SET last_used_at = datetime('now') WHERE key_id = ?",
                    (key_id,),
                )
        except Exception:  # noqa: BLE001
            pass

    def revoke_api_key(self, key_id: str) -> bool:
        """Mark an api_key as disabled. Returns True if a row was updated."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET enabled = 0 WHERE key_id = ?",
                (key_id,),
            )
        return cur.rowcount > 0

    def delete_api_key(self, key_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM api_keys WHERE key_id = ?", (key_id,))
        return cur.rowcount > 0

    # ── Device profile + state (Phase 8) ─────────────────────────────────

    def get_device_profile_state(self, device_id: str) -> dict[str, Any] | None:
        """Return ``{profile, state, deployment_id}`` for a device, or None."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT device_id, profile, state, deployment_id
                FROM devices WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_device_profile(self, device_id: str, profile: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE devices SET profile = ? WHERE device_id = ?",
                (profile, device_id),
            )
        return cur.rowcount > 0

    def set_device_state(
        self,
        device_id: str,
        new_state: str,
        transitioned_by: str | None = None,
        reason: str | None = None,
    ) -> tuple[bool, str | None]:
        """Atomic-ish state change with audit logging.

        Returns ``(success, previous_state)``. ``previous_state`` is None
        if the device was not found.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT state, deployment_id FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if row is None:
                return False, None
            prev = row["state"]
            deployment_id = row["deployment_id"]
            conn.execute(
                "UPDATE devices SET state = ? WHERE device_id = ?",
                (new_state, device_id),
            )
            conn.execute(
                """
                INSERT INTO state_transitions
                    (target_kind, target_id, deployment_id,
                     from_state, to_state, transitioned_by, reason)
                VALUES ('device', ?, ?, ?, ?, ?, ?)
                """,
                (device_id, deployment_id, prev, new_state, transitioned_by, reason),
            )
        return True, prev

    def set_deployment_state(
        self,
        deployment_id: str,
        new_state: str,
        transitioned_by: str | None = None,
        reason: str | None = None,
    ) -> tuple[bool, str | None]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT state FROM deployments WHERE deployment_id = ?",
                (deployment_id,),
            ).fetchone()
            if row is None:
                return False, None
            prev = row["state"]
            conn.execute(
                "UPDATE deployments SET state = ? WHERE deployment_id = ?",
                (new_state, deployment_id),
            )
            conn.execute(
                """
                INSERT INTO state_transitions
                    (target_kind, target_id, deployment_id,
                     from_state, to_state, transitioned_by, reason)
                VALUES ('deployment', ?, ?, ?, ?, ?, ?)
                """,
                (deployment_id, deployment_id, prev, new_state,
                 transitioned_by, reason),
            )
        return True, prev

    def get_deployment_state(self, deployment_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT state FROM deployments WHERE deployment_id = ?",
                (deployment_id,),
            ).fetchone()
        return row["state"] if row else None

    def list_state_transitions(
        self,
        target_kind: str | None = None,
        target_id: str | None = None,
        deployment_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_kind:
            clauses.append("target_kind = ?")
            params.append(target_kind)
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if deployment_id:
            clauses.append("deployment_id = ?")
            params.append(deployment_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT transition_id, target_kind, target_id, deployment_id,
                       from_state, to_state, transitioned_by, reason,
                       transitioned_at
                FROM state_transitions
                {where}
                ORDER BY transitioned_at DESC, transition_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Schedules (Phase 9) ───────────────────────────────────────────────

    def add_schedule(self, schedule: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO schedules
                    (schedule_id, deployment_id, name, cron_expr,
                     starts_at, ends_at, action_type, action_payload_json,
                     enabled, next_run_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule["schedule_id"],
                    schedule.get("deployment_id", "default"),
                    schedule["name"],
                    schedule.get("cron_expr"),
                    schedule.get("starts_at"),
                    schedule.get("ends_at"),
                    schedule["action_type"],
                    json.dumps(schedule.get("action_payload", {}), sort_keys=True),
                    1 if schedule.get("enabled", True) else 0,
                    schedule.get("next_run_at"),
                ),
            )

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT schedule_id, deployment_id, name, cron_expr,
                       starts_at, ends_at, action_type, action_payload_json,
                       enabled, created_at, last_run_at, next_run_at
                FROM schedules WHERE schedule_id = ?
                """,
                (schedule_id,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        d["action_payload"] = json.loads(d.pop("action_payload_json") or "{}")
        return d

    def list_schedules(
        self,
        enabled_only: bool = False,
        deployment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if enabled_only:
            clauses.append("enabled = 1")
        if deployment_id:
            clauses.append("deployment_id = ?")
            params.append(deployment_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT schedule_id, deployment_id, name, cron_expr,
                       starts_at, ends_at, action_type, action_payload_json,
                       enabled, created_at, last_run_at, next_run_at
                FROM schedules {where} ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d["enabled"] = bool(d["enabled"])
            d["action_payload"] = json.loads(d.pop("action_payload_json") or "{}")
            out.append(d)
        return out

    def update_schedule(self, schedule_id: str, updates: dict[str, Any]) -> bool:
        allowed = {"name", "cron_expr", "starts_at", "ends_at",
                   "action_type", "enabled"}
        sets: list[str] = []
        params: list[Any] = []
        for key, val in updates.items():
            if key not in allowed:
                continue
            if key == "enabled":
                val = 1 if val else 0
            sets.append(f"{key} = ?")
            params.append(val)
        if "action_payload" in updates:
            sets.append("action_payload_json = ?")
            params.append(json.dumps(updates["action_payload"], sort_keys=True))
        if not sets:
            return False
        params.append(schedule_id)
        with self.connect() as conn:
            cur = conn.execute(
                f"UPDATE schedules SET {', '.join(sets)} WHERE schedule_id = ?",
                params,
            )
        return cur.rowcount > 0

    def update_schedule_run_times(
        self,
        schedule_id: str,
        last_run_at: str | None,
        next_run_at: str | None,
    ) -> None:
        """Best-effort update of last_run_at / next_run_at after a tick."""
        try:
            with self.connect() as conn:
                conn.execute(
                    "UPDATE schedules SET last_run_at = ?, next_run_at = ? WHERE schedule_id = ?",
                    (last_run_at, next_run_at, schedule_id),
                )
        except Exception:  # noqa: BLE001
            pass

    def delete_schedule(self, schedule_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM schedules WHERE schedule_id = ?",
                                (schedule_id,))
        return cur.rowcount > 0

    def record_schedule_run(self, run: Any) -> None:
        """Insert a row into schedule_runs. *run* can be a ScheduleRunResult dataclass
        or a plain dict with the same fields."""
        if isinstance(run, dict):
            schedule_id = run["schedule_id"]
            status = run["status"]
            detail = run.get("detail", {})
            error = run.get("error")
        else:
            schedule_id = run.schedule_id
            status = run.status
            detail = getattr(run, "detail", {}) or {}
            error = getattr(run, "error", None)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO schedule_runs
                    (schedule_id, status, detail_json, error)
                VALUES (?, ?, ?, ?)
                """,
                (schedule_id, status, json.dumps(detail, sort_keys=True), error),
            )

    def list_schedule_runs(
        self,
        schedule_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if schedule_id:
            clauses.append("schedule_id = ?")
            params.append(schedule_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT run_id, schedule_id, status, detail_json, error, ran_at
                FROM schedule_runs {where} ORDER BY ran_at DESC, run_id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d["detail"] = json.loads(d.pop("detail_json") or "{}")
            out.append(d)
        return out

    # ── Alert rules ───────────────────────────────────────────────────────

    def add_alert_rule(self, rule: dict[str, Any]) -> None:
        """Insert a new alert rule row."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_rules
                    (rule_id, name, label, min_confidence, species_pattern,
                     device_id, webhook_url, enabled, required_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    rule.get("required_state"),
                ),
            )

    def get_alert_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Return a single alert rule by rule_id, or None."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT rule_id, name, label, min_confidence, species_pattern,
                       device_id, webhook_url, enabled, created_at, required_state
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
                       device_id, webhook_url, enabled, created_at, required_state
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
                   "device_id", "webhook_url", "enabled", "required_state"}
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
