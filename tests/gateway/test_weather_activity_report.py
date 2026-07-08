"""Tests for the weather–activity correlation report (pure builder)."""

from clawcam_gateway.analytics.weather_activity import build_weather_activity_report


def _det(ts, subject="deer"):
    return {"top_species": subject, "ran_at": ts}


def _rd(ts, t):
    return {"timestamp": ts, "temperature_c": t}


def test_no_readings_message():
    r = build_weather_activity_report([_det("2026-05-01T12:00:00+00:00")], [])
    assert r["readings_used"] == 0
    assert "no readings" in r["message"]
    assert r["bins"] == []


def test_exposure_and_rate_and_positive_correlation():
    # Readings span 10..20°C evenly; detections cluster at the warm readings →
    # rate should rise with temperature (positive correlation).
    readings = [_rd(f"2026-05-01T{h:02d}:00:00+00:00", 10.0 + h) for h in range(0, 11)]  # 10..20
    # Detections only near the warmest readings (hours 9,10 → ~19,20°C).
    dets = [_det(f"2026-05-01T09:{m:02d}:00+00:00") for m in range(0, 6)] + \
           [_det(f"2026-05-01T10:{m:02d}:00+00:00") for m in range(0, 6)]
    r = build_weather_activity_report(dets, readings, bins=5)
    assert r["readings_used"] == 11
    assert r["matched_detections"] == 12
    assert r["correlation"] is not None and r["correlation"] > 0.5
    # Peak rate is in the warm bin.
    assert r["peak_bin"]["hi"] >= 18.0


def test_unmatched_when_no_reading_within_gap():
    readings = [_rd("2026-05-01T00:00:00+00:00", 15.0)]
    # Detection 10 hours later → beyond the 120-min default gap → unmatched.
    r = build_weather_activity_report([_det("2026-05-01T10:00:00+00:00")], readings)
    assert r["matched_detections"] == 0
    assert r["unmatched_detections"] == 1


def test_bins_cover_reading_range_and_exposure_sums():
    readings = [_rd(f"2026-05-01T{h:02d}:00:00+00:00", 10.0 + h) for h in range(0, 11)]
    r = build_weather_activity_report([], readings, bins=5)
    assert sum(b["exposure"] for b in r["bins"]) == 11
    assert r["bins"][0]["lo"] == 10.0
    assert r["bins"][-1]["hi"] == 20.0
    assert all(b["detections"] == 0 for b in r["bins"])  # no detections


def test_humidity_quantity_selectable():
    readings = [{"timestamp": f"2026-05-01T{h:02d}:00:00+00:00", "humidity_percent": 50.0 + h}
                for h in range(0, 6)]
    r = build_weather_activity_report([_det("2026-05-01T02:00:00+00:00")], readings,
                                      quantity="humidity_percent", bins=3)
    assert r["quantity"] == "humidity_percent"
    assert r["matched_detections"] == 1
    assert r["readings_used"] == 6
