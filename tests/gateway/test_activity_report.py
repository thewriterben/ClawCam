"""Species activity report tests — pure, import-isolated (no DB/framework)."""

from __future__ import annotations

import sys
from pathlib import Path

_GW = Path(__file__).parents[2] / "gateway"
if str(_GW) not in sys.path:
    sys.path.insert(0, str(_GW))

from clawcam_gateway.analytics.activity import build_activity_report


def _det(subject: str, hour: int, *, label: bool = False) -> dict:
    key = "top_label" if label else "top_species"
    return {key: subject, "ran_at": f"2026-05-14T{hour:02d}:30:00Z"}


def test_empty_report():
    r = build_activity_report([])
    assert r["total_detections"] == 0
    assert r["distinct_subjects"] == 0
    assert r["species"] == []


def test_counts_peak_and_ranking():
    dets = [_det("deer", 22), _det("deer", 22), _det("deer", 1), _det("coyote", 3)]
    r = build_activity_report(dets)
    assert r["total_detections"] == 4
    assert r["distinct_subjects"] == 2
    assert r["species"][0]["subject"] == "deer"  # most frequent first
    assert r["species"][0]["count"] == 3
    assert r["species"][0]["peak_hour"] == 22  # two of three at 22:00
    assert sum(r["species"][0]["hourly"]) == 3


def test_diel_nocturnal():
    dets = [_det("owl", h) for h in (22, 23, 1, 2, 3)]
    assert build_activity_report(dets)["species"][0]["diel_pattern"] == "nocturnal"


def test_diel_diurnal():
    dets = [_det("hawk", h) for h in (9, 10, 11, 12, 14)]
    assert build_activity_report(dets)["species"][0]["diel_pattern"] == "diurnal"


def test_diel_crepuscular():
    dets = [_det("rabbit", h) for h in (5, 6, 17, 18)]
    assert build_activity_report(dets)["species"][0]["diel_pattern"] == "crepuscular"


def test_diel_cathemeral():
    dets = [_det("cat", h) for h in (2, 8, 14, 21)]  # spread across the cycle
    assert build_activity_report(dets)["species"][0]["diel_pattern"] == "cathemeral"


def test_tz_offset_shifts_hour_of_day():
    # A 22:00 UTC detection is 14:00 in US Pacific (-8) → daytime, peak hour 14.
    r = build_activity_report([_det("deer", 22)], tz_offset_hours=-8)
    assert r["species"][0]["peak_hour"] == 14


def test_label_fallback_and_first_last_seen():
    dets = [_det("person", 8, label=True), _det("person", 20, label=True)]
    sp = build_activity_report(dets)["species"][0]
    assert sp["subject"] == "person"  # falls back to top_label when no species
    assert sp["first_seen"] < sp["last_seen"]
    assert sp["count"] == 2
