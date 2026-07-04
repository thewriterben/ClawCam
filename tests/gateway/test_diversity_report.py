"""Species diversity report tests — pure, import-isolated (no DB/framework)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

_GW = Path(__file__).parents[2] / "gateway"
if str(_GW) not in sys.path:
    sys.path.insert(0, str(_GW))

from clawcam_gateway.analytics.diversity import build_diversity_report


def _dets(counts: dict[str, int]) -> list[dict]:
    out = []
    for subject, n in counts.items():
        out.extend({"top_species": subject} for _ in range(n))
    return out


def test_empty_report():
    r = build_diversity_report([])
    assert r["total_detections"] == 0
    assert r["richness"] == 0
    assert r["shannon_index"] == 0.0
    assert r["evenness"] == 0.0
    assert r["dominant_subject"] is None
    assert r["species"] == []


def test_single_species_is_maximally_dominated():
    r = build_diversity_report(_dets({"deer": 4}))
    assert r["richness"] == 1
    assert r["shannon_index"] == 0.0        # one species → no uncertainty
    assert r["evenness"] == 1.0             # trivially "even"
    assert r["simpson_dominance"] == 1.0
    assert r["dominant_subject"] == "deer"


def test_two_equal_species_are_perfectly_even():
    r = build_diversity_report(_dets({"deer": 2, "coyote": 2}))
    assert r["richness"] == 2
    assert r["shannon_index"] == round(math.log(2), 4)  # ln 2
    assert r["evenness"] == 1.0
    assert r["simpson_dominance"] == 0.5


def test_skewed_community_is_uneven():
    r = build_diversity_report(_dets({"deer": 9, "coyote": 1}))
    assert r["richness"] == 2
    assert r["evenness"] < 0.6             # dominated by deer
    assert r["dominant_subject"] == "deer"
    assert r["species"][0] == {"subject": "deer", "count": 9, "proportion": 0.9}


def test_ranking_and_label_fallback():
    dets = _dets({"deer": 3}) + [{"top_label": "person"}]
    r = build_diversity_report(dets)
    assert r["richness"] == 2
    assert [s["subject"] for s in r["species"]] == ["deer", "person"]  # by count desc
