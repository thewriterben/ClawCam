"""Tests for daily anomaly detection (pure, import-isolated)."""

from clawcam_gateway.analytics.anomaly import build_anomaly_report


def _dets(day, n, hour=12):
    return [{"top_species": "deer", "ran_at": f"2026-05-{day:02d}T{hour:02d}:00:00Z"} for _ in range(n)]


def test_empty_series():
    r = build_anomaly_report([])
    assert r["days"] == 0
    assert r["anomalies"] == 0
    assert r["series"] == []


def test_flat_series_has_no_anomalies():
    dets = _dets(1, 5) + _dets(2, 5) + _dets(3, 5)
    r = build_anomaly_report(dets)
    assert r["stdev"] == 0.0
    assert r["anomalies"] == 0
    assert all(s["kind"] == "normal" for s in r["series"])


def test_spike_day_is_flagged():
    # Five quiet days of 2, one loud day of 40 → clear spike.
    dets = sum((_dets(d, 2) for d in range(1, 6)), []) + _dets(6, 40)
    r = build_anomaly_report(dets, z_threshold=2.0)
    assert r["days"] == 6
    spikes = [s for s in r["series"] if s["kind"] == "spike"]
    assert len(spikes) == 1
    assert spikes[0]["date"] == "2026-05-06"
    assert spikes[0]["z"] > 2.0
    assert r["busiest_day"] == "2026-05-06"


def test_drop_day_is_flagged():
    # Five busy days of 20, one silent-ish day of 1 → drop.
    dets = sum((_dets(d, 20) for d in range(1, 6)), []) + _dets(6, 1)
    r = build_anomaly_report(dets, z_threshold=1.5)
    drops = [s for s in r["series"] if s["kind"] == "drop"]
    assert len(drops) == 1
    assert drops[0]["date"] == "2026-05-06"
    assert drops[0]["z"] < 0
    assert r["quietest_day"] == "2026-05-06"


def test_series_is_date_sorted_and_counts_right():
    dets = _dets(3, 1) + _dets(1, 2) + _dets(2, 3)
    r = build_anomaly_report(dets)
    dates = [s["date"] for s in r["series"]]
    assert dates == ["2026-05-01", "2026-05-02", "2026-05-03"]
    assert [s["count"] for s in r["series"]] == [2, 3, 1]
    assert r["mean"] == 2.0


def test_bad_timestamps_ignored():
    dets = _dets(1, 2) + [{"top_species": "deer", "ran_at": "nope"}, {"top_species": "deer"}]
    r = build_anomaly_report(dets)
    assert r["ignored_no_timestamp"] == 2
    assert r["days"] == 1


def test_threshold_controls_sensitivity():
    dets = sum((_dets(d, 5) for d in range(1, 5)), []) + _dets(5, 11)
    lenient = build_anomaly_report(dets, z_threshold=2.5)
    strict = build_anomaly_report(dets, z_threshold=1.5)
    # Same data, looser threshold flags fewer days than the tighter one.
    assert strict["anomalies"] >= lenient["anomalies"]
