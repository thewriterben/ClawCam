"""Tests for persisting a scenario detection stream into a database.

Two layers: a fake-DB unit check of the loader's call pattern, and a real
GatewayDatabase round-trip proving the seeded stream lands as analytics-visible
rows with their historic ``ran_at`` preserved.
"""

from clawcam_gateway.simulator.scenario import ScenarioSpec, SpeciesProfile, build_detection_stream
from clawcam_gateway.simulator.loader import load_stream_into_db


class _FakeDB:
    def __init__(self):
        self.devices = []
        self.events = []
        self.results = []
        self.reviews = []
        self._next_id = 0

    def upsert_device(self, payload):
        self.devices.append(payload)

    def add_event(self, payload):
        self.events.append(payload)

    def save_inference_result(self, event_id, media_path, result, ran_at=None):
        self._next_id += 1
        self.results.append({"id": self._next_id, "event_id": event_id,
                             "ran_at": ran_at, "result": result.to_dict()})
        return self._next_id

    def set_review_state(self, result_id, state, reviewer=None, note=None):
        self.reviews.append((result_id, state))


def _stream(**kw):
    spec = ScenarioSpec(species=[SpeciesProfile("deer", daily_rate=8)], days=4, seed=5, **kw)
    return build_detection_stream(spec)


def test_loader_writes_device_once_and_event_per_row():
    stream = _stream()
    db = _FakeDB()
    counts = load_stream_into_db(db, stream)
    assert counts["devices"] == 1              # single device upserted once
    assert counts["events"] == len(stream)     # one event per detection
    assert counts["results"] == len(stream)
    assert len(db.devices) == 1


def test_loader_backdates_ran_at_to_row_timestamp():
    stream = _stream()
    db = _FakeDB()
    load_stream_into_db(db, stream)
    assert [r["ran_at"] for r in db.results] == [row["ran_at"] for row in stream]
    # And the result carries the row's species/label through to_dict().
    assert db.results[0]["result"]["top_species"] == "deer"


def test_reviewed_frac_labels_are_deterministic_and_bounded():
    stream = _stream()
    a, b = _FakeDB(), _FakeDB()
    ca = load_stream_into_db(a, stream, reviewed_frac=0.5, review_seed=7)
    cb = load_stream_into_db(b, stream, reviewed_frac=0.5, review_seed=7)
    assert a.reviews == b.reviews                    # deterministic
    assert 0 < ca["reviewed"] <= len(stream)
    assert ca["reviewed"] == cb["reviewed"]
    for _id, state in a.reviews:
        assert state in {"verified", "rejected"}


def test_zero_reviewed_frac_labels_nothing():
    db = _FakeDB()
    counts = load_stream_into_db(db, _stream(), reviewed_frac=0.0)
    assert counts["reviewed"] == 0
    assert db.reviews == []


def test_real_db_roundtrip_is_analytics_visible(tmp_path):
    from clawcam_gateway.storage.database import GatewayDatabase

    stream = _stream(spike_days=[3])
    db = GatewayDatabase(str(tmp_path / "sim.db"))
    counts = load_stream_into_db(db, stream, reviewed_frac=0.3, review_seed=1)

    rows = db.list_inference_results(limit=10_000)
    assert len(rows) == counts["results"] == len(stream)
    # Historic ran_at survived the round-trip (not stamped to "now").
    assert {r["ran_at"] for r in rows} == {row["ran_at"] for row in stream}
    assert all(r["top_species"] == "deer" for r in rows)


def test_clear_deployment_gives_a_clean_slate(tmp_path):
    from clawcam_gateway.storage.database import GatewayDatabase

    db = GatewayDatabase(str(tmp_path / "sim.db"))
    stream = _stream()
    load_stream_into_db(db, stream)
    assert len(db.list_inference_results(limit=10_000)) == len(stream)

    dep = stream[0]["deployment_id"]
    cleared = db.clear_deployment_detections(dep)
    assert cleared["inference_results"] == len(stream)
    assert cleared["events"] == len(stream)
    assert db.list_inference_results(limit=10_000) == []

    # Re-seeding after a clear does not double up.
    load_stream_into_db(db, stream)
    assert len(db.list_inference_results(limit=10_000)) == len(stream)


def test_real_db_stream_feeds_anomaly_report(tmp_path):
    from clawcam_gateway.storage.database import GatewayDatabase
    from clawcam_gateway.analytics.anomaly import build_anomaly_report

    stream = _stream(spike_days=[3])
    db = GatewayDatabase(str(tmp_path / "sim.db"))
    load_stream_into_db(db, stream)

    rows = db.list_inference_results(limit=10_000)
    report = build_anomaly_report(rows, z_threshold=1.5)
    kinds = [s["kind"] for s in report["series"]]
    assert "spike" in kinds  # the injected day-3 surge is detected end-to-end
