"""Conservation Grid G0: device positions (the mappable nodes within a site)."""

import json

from clawcam_gateway.storage.database import GatewayDatabase

_SQUARE = [[45.4, -122.7], [45.4, -122.5], [45.6, -122.5], [45.6, -122.7]]


def _db(tmp_path):
    return GatewayDatabase(str(tmp_path / "db.sqlite"))


def _device(db, device_id, lat=None, lon=None):
    payload = {
        "device_id": device_id, "device_type": "camera-node", "name": device_id,
        "status": "online", "created_at": "2026-05-01T00:00:00+00:00", "deployment_id": "default",
    }
    if lat is not None:
        payload["location"] = {"latitude": lat, "longitude": lon}
    db.upsert_device(payload)


def test_device_columns_exist(tmp_path):
    db = _db(tmp_path)
    with db.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(devices)").fetchall()}
    assert {"latitude", "longitude"} <= cols


def test_position_populated_on_upsert(tmp_path):
    db = _db(tmp_path)
    _device(db, "n1", 45.5, -122.6)
    pos = db.devices_with_position()
    assert len(pos) == 1
    assert pos[0]["device_id"] == "n1"
    assert pos[0]["latitude"] == 45.5 and pos[0]["longitude"] == -122.6


def test_upsert_without_location_keeps_existing_position(tmp_path):
    db = _db(tmp_path)
    _device(db, "n1", 45.5, -122.6)
    _device(db, "n1")  # re-upsert with no location → COALESCE keeps the position
    pos = db.devices_with_position()
    assert len(pos) == 1 and pos[0]["latitude"] == 45.5


def test_set_device_position(tmp_path):
    db = _db(tmp_path)
    _device(db, "n1")
    assert db.set_device_position("n1", 45.55, -122.61) is True
    assert db.set_device_position("nope", 1.0, 2.0) is False
    assert db.devices_with_position()[0]["latitude"] == 45.55


def test_devices_in_site(tmp_path):
    db = _db(tmp_path)
    db.upsert_site({"site_id": "s1", "boundary": _SQUARE})
    _device(db, "inside", 45.5, -122.6)
    _device(db, "outside", 10.0, 10.0)
    _device(db, "nogeo")  # no position → excluded
    ids = {d["device_id"] for d in db.devices_in_site("s1")}
    assert ids == {"inside"}


def test_devices_in_unknown_site_is_empty(tmp_path):
    db = _db(tmp_path)
    _device(db, "n1", 45.5, -122.6)
    assert db.devices_in_site("nope") == []


def test_backfill_from_legacy_payload(tmp_path):
    path = str(tmp_path / "db.sqlite")
    db = GatewayDatabase(path)
    payload = {
        "device_id": "legacy", "device_type": "camera-node", "name": "legacy",
        "status": "online", "created_at": "2026-05-01T00:00:00+00:00", "deployment_id": "default",
        "location": {"latitude": 48.1, "longitude": -1.7},
    }
    # Legacy row: geo only in payload_json, columns NULL.
    with db.connect() as c:
        c.execute(
            "INSERT INTO devices (device_id, device_type, name, status, payload_json, "
            "created_at, deployment_id) VALUES (?,?,?,?,?,?,?)",
            ("legacy", "camera-node", "legacy", "online", json.dumps(payload),
             "2026-05-01T00:00:00+00:00", "default"),
        )
    db2 = GatewayDatabase(path)  # re-open runs migrate() backfill
    pos = {d["device_id"]: d for d in db2.devices_with_position()}
    assert pos["legacy"]["latitude"] == 48.1 and pos["legacy"]["longitude"] == -1.7
