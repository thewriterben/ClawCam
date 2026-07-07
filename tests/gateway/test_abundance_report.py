"""Tests for the relative abundance index (RAI) report (pure builder)."""

from clawcam_gateway.analytics.abundance import build_abundance_report


def _d(subject, date, hour=12):
    return {"top_species": subject, "ran_at": f"{date}T{hour:02d}:00:00+00:00"}


def test_empty_has_zero_effort_and_no_species():
    r = build_abundance_report([])
    assert r["trap_days"] == 0
    assert r["species"] == []
    assert r["total_detections"] == 0


def test_span_effort_and_rai():
    # deer 4 detections, coyote 1, over an inclusive 10-day span (05-01..05-10).
    rows = (
        [_d("deer", "2026-05-01"), _d("deer", "2026-05-03"),
         _d("deer", "2026-05-06"), _d("deer", "2026-05-10")]
        + [_d("coyote", "2026-05-05")]
    )
    r = build_abundance_report(rows)
    assert r["trap_days"] == 10                 # inclusive first→last span
    assert r["trap_days_source"] == "span"
    deer = next(s for s in r["species"] if s["subject"] == "deer")
    coyote = next(s for s in r["species"] if s["subject"] == "coyote")
    assert deer["count"] == 4
    assert deer["rai"] == 40.0                  # 4 / 10 * 100
    assert deer["days_present"] == 4
    assert coyote["rai"] == 10.0
    # Ranked by RAI descending.
    assert r["species"][0]["subject"] == "deer"


def test_provided_trap_days_overrides_span():
    rows = [_d("deer", "2026-05-01"), _d("deer", "2026-05-02")]
    r = build_abundance_report(rows, trap_days=20)
    assert r["trap_days"] == 20
    assert r["trap_days_source"] == "provided"
    assert r["species"][0]["rai"] == 10.0       # 2 / 20 * 100


def test_single_day_span_is_one_trap_day():
    r = build_abundance_report([_d("deer", "2026-05-01"), _d("deer", "2026-05-01", hour=20)])
    assert r["trap_days"] == 1                   # same day → span of 1, not 0
    assert r["species"][0]["rai"] == 200.0       # 2 / 1 * 100


def test_rows_without_timestamp_are_ignored():
    rows = [_d("deer", "2026-05-01"), {"top_species": "deer", "ran_at": ""}]
    r = build_abundance_report(rows)
    assert r["total_detections"] == 1
