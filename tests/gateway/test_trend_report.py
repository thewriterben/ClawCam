"""Detection trend report tests — pure, import-isolated (no DB/framework)."""

from __future__ import annotations

import sys
from pathlib import Path

_GW = Path(__file__).parents[2] / "gateway"
if str(_GW) not in sys.path:
    sys.path.insert(0, str(_GW))

from clawcam_gateway.analytics.trends import build_trend_report


def _dets(subject: str, day_counts: dict[int, int]) -> list[dict]:
    """`{day_of_may: count}` -> that many detection rows on each day."""
    out = []
    for day, count in day_counts.items():
        for _ in range(count):
            out.append({"top_species": subject, "ran_at": f"2026-05-{day:02d}T12:00:00Z"})
    return out


def test_empty_report():
    r = build_trend_report([])
    assert r["total_detections"] == 0
    assert r["distinct_subjects"] == 0
    assert r["daily_totals"] == []
    assert r["species"] == []


def test_rising_trend():
    dets = _dets("deer", {11: 1, 12: 1, 13: 3, 14: 4})
    sp = build_trend_report(dets)["species"][0]
    assert sp["trend"] == "rising"
    assert sp["total"] == 9
    assert sp["busiest_day"] == "2026-05-14"
    assert sp["first_day"] == "2026-05-11"
    assert sp["last_day"] == "2026-05-14"


def test_falling_trend():
    dets = _dets("deer", {11: 4, 12: 3, 13: 1, 14: 1})
    assert build_trend_report(dets)["species"][0]["trend"] == "falling"


def test_steady_trend_odd_days():
    # Even rate across an odd number of days must read as steady, not biased-rising.
    dets = _dets("deer", {11: 2, 12: 2, 13: 2})
    assert build_trend_report(dets)["species"][0]["trend"] == "steady"


def test_daily_totals_and_ranking():
    dets = _dets("deer", {11: 2, 12: 1}) + _dets("coyote", {11: 1})
    r = build_trend_report(dets)
    assert r["total_detections"] == 4
    assert r["distinct_subjects"] == 2
    assert r["days_span"] == 2
    assert r["species"][0]["subject"] == "deer"  # most detections first
    totals = {d["date"]: d["count"] for d in r["daily_totals"]}
    assert totals == {"2026-05-11": 3, "2026-05-12": 1}


def test_tz_offset_shifts_calendar_day():
    # 01:00 UTC on the 14th is 17:00 on the 13th in US Pacific (-8).
    dets = [{"top_species": "deer", "ran_at": "2026-05-14T01:00:00Z"}]
    sp = build_trend_report(dets, tz_offset_hours=-8)["species"][0]
    assert sp["first_day"] == "2026-05-13"
