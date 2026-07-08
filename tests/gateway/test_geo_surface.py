"""Conservation Grid G0: the geo/site REST + MCP-catalog surface.

Exercises the site CRUD + point-in-polygon events endpoints via TestClient, and
asserts the two new read tools are present (and auto-approved) in the tool catalog.
Data is seeded through a second DB handle on the same sqlite file.
"""

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.storage.database import GatewayDatabase


_SQUARE = [[45.4, -122.7], [45.4, -122.5], [45.6, -122.5], [45.6, -122.7]]


def _app_and_db(tmp_path):
    db_path = tmp_path / "db.sqlite"
    app = create_app(GatewayConfig(database_path=db_path, media_dir=tmp_path / "media"))
    return TestClient(app), GatewayDatabase(str(db_path))


def _event(event_id, lat, lon):
    return {
        "event_id": event_id, "event_type": "detection", "device_id": "node-1",
        "timestamp": "2026-05-01T12:00:00+00:00", "source": "test", "deployment_id": "default",
        "location": {"latitude": lat, "longitude": lon, "altitude_m": 100.0},
    }


def test_site_crud_and_list(tmp_path):
    client, _ = _app_and_db(tmp_path)
    r = client.post("/api/v1/sites", json={"data": {"site_id": "s1", "name": "North Ridge", "boundary": _SQUARE}})
    assert r.status_code == 200, r.text
    assert r.json()["site"]["name"] == "North Ridge"

    r = client.get("/api/v1/sites")
    ids = {s["site_id"] for s in r.json()["sites"]}
    assert "s1" in ids

    r = client.get("/api/v1/sites/s1")
    assert r.status_code == 200
    assert abs(r.json()["site"]["origin_lat"] - 45.5) < 1e-9  # centroid default

    assert client.get("/api/v1/sites/nope").status_code == 404


def test_site_events_point_in_polygon(tmp_path):
    client, db = _app_and_db(tmp_path)
    db.upsert_device({
        "device_id": "node-1", "device_type": "camera-node", "name": "n",
        "status": "online", "created_at": "2026-05-01T00:00:00+00:00", "deployment_id": "default",
    })
    db.upsert_site({"site_id": "s1", "boundary": _SQUARE})
    db.add_event(_event("inside", 45.5, -122.6))
    db.add_event(_event("outside", 10.0, 10.0))

    r = client.get("/api/v1/sites/s1/events")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["event_id"] == "inside"


def test_deployment_site_link_endpoint(tmp_path):
    client, db = _app_and_db(tmp_path)
    db.add_deployment({"deployment_id": "d1", "name": "D1"})
    db.upsert_site({"site_id": "s1", "boundary": _SQUARE})
    r = client.put("/api/v1/deployments/d1/site", json={"data": {"site_id": "s1"}})
    assert r.status_code == 200, r.text
    assert r.json()["site_id"] == "s1"


def test_new_tools_in_catalog_and_auto_approved(tmp_path):
    client, _ = _app_and_db(tmp_path)
    tools = {t["name"]: t for t in client.get("/api/v1/tools").json()["tools"]}
    for name in ("list_sites", "get_site_events"):
        assert name in tools, f"{name} missing from tool catalog"
        assert tools[name]["approval_required"] is False  # read-only → auto-approved
