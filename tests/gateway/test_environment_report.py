"""Tests for the environmental telemetry report (pure builder)."""

from clawcam_gateway.analytics.environment import build_environment_report


def _r(ts, t=None, h=None, p=None):
    return {"timestamp": ts, "temperature_c": t, "humidity_percent": h, "pressure_hpa": p}


def test_empty_has_no_quantities():
    r = build_environment_report([])
    assert r["reading_count"] == 0
    assert r["quantities"] == {}


def test_temperature_stats_and_daily():
    rows = [
        _r("2026-05-01T06:00:00+00:00", t=10.0),
        _r("2026-05-01T18:00:00+00:00", t=20.0),
        _r("2026-05-02T12:00:00+00:00", t=30.0),
    ]
    q = build_environment_report(rows)["quantities"]["temperature_c"]
    assert q["count"] == 3
    assert q["min"] == 10.0 and q["max"] == 30.0
    assert q["mean"] == 20.0
    assert q["latest"] == 30.0            # newest timestamp
    assert q["trend"] == "rising"
    assert q["daily"] == [
        {"date": "2026-05-01", "mean": 15.0},
        {"date": "2026-05-02", "mean": 30.0},
    ]


def test_only_present_quantities_appear():
    rows = [_r("2026-05-01T06:00:00+00:00", h=80.0)]
    q = build_environment_report(rows)["quantities"]
    assert set(q) == {"humidity_percent"}
    assert q["humidity_percent"]["latest"] == 80.0


def test_falling_and_steady_trend():
    falling = [_r(f"2026-05-01T0{i}:00:00+00:00", p=1020.0 - i) for i in range(6)]
    assert build_environment_report(falling)["quantities"]["pressure_hpa"]["trend"] == "falling"
    steady = [_r(f"2026-05-01T0{i}:00:00+00:00", t=15.0) for i in range(6)]
    assert build_environment_report(steady)["quantities"]["temperature_c"]["trend"] == "steady"


def test_tz_offset_shifts_daily_bucketing():
    # 23:00 UTC on 05-01 with +2h → local 01:00 on 05-02.
    rows = [_r("2026-05-01T23:00:00+00:00", t=12.0)]
    q = build_environment_report(rows, tz_offset_hours=2)["quantities"]["temperature_c"]
    assert q["daily"][0]["date"] == "2026-05-02"


def test_order_independent():
    a = [_r("2026-05-01T06:00:00+00:00", t=10.0), _r("2026-05-02T06:00:00+00:00", t=20.0)]
    b = list(reversed(a))
    assert build_environment_report(a) == build_environment_report(b)
