"""CSV/JSON data export for ClawCam gateway records.

Provides streaming-friendly helpers that turn gateway DB rows into CSV text.
Used by REST endpoints and the export_detections_csv MCP tool.

Design
------
- Returns plain ``str`` so callers can choose to write to disk, stream as
  a FastAPI ``StreamingResponse``, or embed in an MCP text result.
- No mandatory dependencies beyond the standard library.
- All timestamps are passed through as-is (ISO 8601 UTC strings from SQLite).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from clawcam_gateway.storage.database import GatewayDatabase


# ── Events CSV ────────────────────────────────────────────────────────────────

EVENTS_COLUMNS = [
    "event_id",
    "event_type",
    "device_id",
    "timestamp",
    "time_source",
    "source",
    "media_count",
    "trigger",
]


def events_to_csv(events: list[dict]) -> str:
    """Serialise a list of event payloads to CSV text (including header row)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EVENTS_COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for event in events:
        row = {
            "event_id": event.get("event_id", ""),
            "event_type": event.get("event_type", ""),
            "device_id": event.get("device_id", ""),
            "timestamp": event.get("timestamp", ""),
            "time_source": event.get("time_source", ""),
            "source": event.get("source", ""),
            "media_count": len(event.get("media", [])),
            "trigger": event.get("metadata", {}).get("trigger", ""),
        }
        writer.writerow(row)
    return buf.getvalue()


# ── Detections CSV ────────────────────────────────────────────────────────────

DETECTIONS_COLUMNS = [
    "event_id",
    "ran_at",
    "model_name",
    "model_version",
    "top_label",
    "top_confidence",
    "top_species",
    "media_path",
    "detection_count",
]


def detections_to_csv(results: list[dict]) -> str:
    """Serialise a list of inference result dicts to CSV text."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=DETECTIONS_COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for r in results:
        row = {
            "event_id": r.get("event_id", ""),
            "ran_at": r.get("ran_at", ""),
            "model_name": r.get("model_name", ""),
            "model_version": r.get("model_version", ""),
            "top_label": r.get("top_label", ""),
            "top_confidence": r.get("top_confidence", ""),
            "top_species": r.get("top_species", ""),
            "media_path": r.get("media_path", ""),
            "detection_count": len(r.get("detections", [])),
        }
        writer.writerow(row)
    return buf.getvalue()


# ── Convenience DB wrappers ───────────────────────────────────────────────────

def export_events_csv(
    db: "GatewayDatabase",
    limit: int = 1000,
    device_id: str | None = None,
) -> str:
    """Fetch recent events from *db* and return them as CSV text."""
    events = db.recent_events(limit=limit)
    if device_id:
        events = [e for e in events if e.get("device_id") == device_id]
    return events_to_csv(events)


def export_detections_csv(
    db: "GatewayDatabase",
    limit: int = 1000,
    label: str | None = None,
    min_confidence: float = 0.0,
    species: str | None = None,
) -> str:
    """Fetch recent inference results from *db* and return them as CSV text."""
    results = db.list_inference_results(
        limit=limit,
        label=label,
        min_confidence=min_confidence,
        species=species,
    )
    return detections_to_csv(results)


def csv_filename(prefix: str) -> str:
    """Return a timestamped filename suitable for Content-Disposition headers."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{ts}.csv"
