"""Conservation Grid G0: geo + environment promoted to queryable columns.

Verifies that latitude/longitude/altitude land on `events` and temperature/
humidity/pressure on `health_records` as real columns (populated on insert and
backfilled from legacy `payload_json`), that a bbox query uses them, and that the
CSV export carries geo.
"""

import json

from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.ingest.export import events_to_csv, EVENTS_COLUMNS


def _device(db, device_id="node-1", deployment_id="default"):
    db.upsert_device({
        "device_id": device_id, "device_type": "camera-node", "name": "n",
        "status": "online", "created_at": "2026-05-01T00:00:00+00:00",
        "deployment_id": deployment_id,
    })


def _event(event_id, lat, lon, alt=100.0, device_id="node-1", deployment_id="default"):
    return {
        "event_id": event_id, "event_type": "detection", "device_id": device_id,
        "timestamp": "2026-05-01T12:00:00+00:00", "source": "test",
        "deployment_id": deployment_id,
        "location": {"latitude": lat, "longitude": lon, "altitude_m": alt},
    }


def _cols(db, table):
    with db.connect() as c:
        return {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def test_columns_exist(tmp_path):
    db = GatewayDatabase(str(tmp_path / "db.sqlite"))
    assert {"latitude", "longitude", "altitude_m"} <= _cols(db, "events")
    assert {"temperature_c", "humidity_percent", "pressure_hpa"} <= _cols(db, "health_records")


def test_event_geo_populated_on_insert(tmp_path):
    db = GatewayDatabase(str(tmp_path / "db.sqlite"))
    _device(db)
    db.add_event(_event("e1", 45.5, -122.6))
    with db.connect() as c:
        row = c.execute(
            "SELECT latitude, longitude, altitude_m FROM events WHERE event_id='e1'"
        ).fetchone()
    assert row["latitude"] == 45.5
    assert row["longitude"] == -122.6
    assert row["altitude_m"] == 100.0


def test_health_environment_populated_on_insert(tmp_path):
    db = GatewayDatabase(str(tmp_path / "db.sqlite"))
    _device(db)
    db.add_health({
        "device_id": "node-1", "timestamp": "2026-05-01T12:00:00+00:00",
        "status": "ok", "deployment_id": "default",
        "environment": {"temperature_c": 12.5, "humidity_percent": 80.0, "pressure_hpa": 1013.2},
    })
    with db.connect() as c:
        row = c.execute(
            "SELECT temperature_c, humidity_percent, pressure_hpa FROM health_records"
        ).fetchone()
    assert row["temperature_c"] == 12.5
    assert row["humidity_percent"] == 80.0
    assert row["pressure_hpa"] == 1013.2


def test_bbox_query_filters_by_location(tmp_path):
    db = GatewayDatabase(str(tmp_path / "db.sqlite"))
    _device(db)
    db.add_event(_event("inside", 45.5, -122.6))
    db.add_event(_event("far", 10.0, 10.0))
    hits = db.events_in_bbox(min_lat=45.0, min_lon=-123.0, max_lat=46.0, max_lon=-122.0)
    ids = {e["event_id"] for e in hits}
    assert "inside" in ids
    assert "far" not in ids


def test_backfill_from_legacy_payload_json(tmp_path):
    path = str(tmp_path / "db.sqlite")
    db = GatewayDatabase(path)
    _device(db)
    # Simulate a legacy row: geo only in payload_json, columns left NULL.
    payload = _event("legacy", 48.1, -1.7)
    with db.connect() as c:
        c.execute(
            "INSERT INTO events (event_id, event_type, device_id, timestamp, source, "
            "payload_json, deployment_id) VALUES (?,?,?,?,?,?,?)",
            ("legacy", "detection", "node-1", payload["timestamp"], "test",
             json.dumps(payload), "default"),
        )
    # Re-open → migrate() runs the backfill UPDATE.
    db2 = GatewayDatabase(path)
    with db2.connect() as c:
        row = c.execute(
            "SELECT latitude, longitude, altitude_m FROM events WHERE event_id='legacy'"
        ).fetchone()
    assert row["latitude"] == 48.1
    assert row["longitude"] == -1.7
    assert row["altitude_m"] == 100.0


def test_no_location_leaves_nulls_and_bbox_excludes(tmp_path):
    db = GatewayDatabase(str(tmp_path / "db.sqlite"))
    _device(db)
    db.add_event({
        "event_id": "nogeo", "event_type": "detection", "device_id": "node-1",
        "timestamp": "2026-05-01T12:00:00+00:00", "source": "test", "deployment_id": "default",
    })
    with db.connect() as c:
        row = c.execute("SELECT latitude FROM events WHERE event_id='nogeo'").fetchone()
    assert row["latitude"] is None
    assert db.events_in_bbox(-90, -180, 90, 180) == []  # world bbox still excludes null-geo


def test_export_csv_includes_geo():
    assert EVENTS_COLUMNS[:9] == [
        "event_id", "event_type", "device_id", "timestamp", "time_source",
        "source", "latitude", "longitude", "altitude_m",
    ]
    csv_text = events_to_csv([_event("e1", 45.5, -122.6)])
    header, first = csv_text.splitlines()[0], csv_text.splitlines()[1]
    assert "latitude" in header and "longitude" in header
    assert "45.5" in first and "-122.6" in first
