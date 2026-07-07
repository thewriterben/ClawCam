"""Conservation Grid G0: first-class survey-area sites + point-in-polygon query."""

from clawcam_gateway.storage.database import GatewayDatabase


def _db(tmp_path):
    return GatewayDatabase(str(tmp_path / "db.sqlite"))


def _device(db):
    db.upsert_device({
        "device_id": "node-1", "device_type": "camera-node", "name": "n",
        "status": "online", "created_at": "2026-05-01T00:00:00+00:00",
        "deployment_id": "default",
    })


def _event(event_id, lat, lon):
    return {
        "event_id": event_id, "event_type": "detection", "device_id": "node-1",
        "timestamp": "2026-05-01T12:00:00+00:00", "source": "test", "deployment_id": "default",
        "location": {"latitude": lat, "longitude": lon, "altitude_m": 100.0},
    }


# A square site around (45.5, -122.6).
_SQUARE = [[45.4, -122.7], [45.4, -122.5], [45.6, -122.5], [45.6, -122.7]]


def test_upsert_get_and_centroid_origin(tmp_path):
    db = _db(tmp_path)
    db.upsert_site({"site_id": "s1", "name": "North Ridge", "boundary": _SQUARE})
    s = db.get_site("s1")
    assert s["name"] == "North Ridge"
    assert len(s["boundary"]) == 4
    assert abs(s["origin_lat"] - 45.5) < 1e-9      # centroid of the square
    assert abs(s["origin_lon"] - (-122.6)) < 1e-9


def test_upsert_is_idempotent_update(tmp_path):
    db = _db(tmp_path)
    db.upsert_site({"site_id": "s1", "name": "Old", "boundary": _SQUARE})
    db.upsert_site({"site_id": "s1", "name": "New", "boundary": _SQUARE})
    assert db.get_site("s1")["name"] == "New"
    assert len(db.list_sites()) == 1


def test_explicit_origin_overrides_centroid(tmp_path):
    db = _db(tmp_path)
    db.upsert_site({"site_id": "s1", "boundary": _SQUARE, "origin_lat": 1.0, "origin_lon": 2.0})
    s = db.get_site("s1")
    assert s["origin_lat"] == 1.0 and s["origin_lon"] == 2.0


def test_deployment_site_link(tmp_path):
    db = _db(tmp_path)
    db.add_deployment({"deployment_id": "d1", "name": "D1"})
    db.upsert_site({"site_id": "s1", "boundary": _SQUARE})
    assert db.site_for_deployment("d1") is None
    db.set_deployment_site("d1", "s1")
    assert db.site_for_deployment("d1") == "s1"
    db.set_deployment_site("d1", None)
    assert db.site_for_deployment("d1") is None


def test_events_in_site_square(tmp_path):
    db = _db(tmp_path)
    _device(db)
    db.upsert_site({"site_id": "s1", "boundary": _SQUARE})
    db.add_event(_event("inside", 45.5, -122.6))
    db.add_event(_event("outside", 10.0, 10.0))
    ids = {e["event_id"] for e in db.events_in_site("s1")}
    assert ids == {"inside"}


def test_events_in_site_triangle_excludes_bbox_corner(tmp_path):
    # Triangle A(0,0) B(0,10) C(10,0): region x>=0,y>=0,x+y<=10.
    db = _db(tmp_path)
    _device(db)
    db.upsert_site({"site_id": "tri", "boundary": [[0.0, 0.0], [0.0, 10.0], [10.0, 0.0]]})
    db.add_event(_event("in", 2.0, 2.0))         # x+y=4 → inside triangle
    db.add_event(_event("bbox_corner", 9.0, 9.0))  # inside bbox, x+y=18 → outside triangle
    ids = {e["event_id"] for e in db.events_in_site("tri")}
    assert ids == {"in"}


def test_unknown_or_boundaryless_site_returns_empty(tmp_path):
    db = _db(tmp_path)
    _device(db)
    db.add_event(_event("e", 45.5, -122.6))
    assert db.events_in_site("nope") == []
    db.upsert_site({"site_id": "empty", "boundary": []})
    assert db.events_in_site("empty") == []
