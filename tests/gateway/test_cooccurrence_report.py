"""Tests for the species co-occurrence report (pure builder)."""

from clawcam_gateway.analytics.cooccurrence import build_cooccurrence_report


def _d(subject, ran_at):
    return {"top_species": subject, "ran_at": ran_at}


def test_empty_and_single_subject_have_no_pairs():
    assert build_cooccurrence_report([])["pairs"] == []
    rows = [_d("deer", "2026-05-01T01:00:00+00:00"), _d("deer", "2026-05-01T02:00:00+00:00")]
    out = build_cooccurrence_report(rows)
    assert out["distinct_subjects"] == 1
    assert out["pairs"] == []
    assert out["strongest"] is None


def test_same_window_pair_scores_high_jaccard():
    # deer and fox always in the same hour window; turkey in separate windows.
    rows = [
        _d("deer", "2026-05-01T01:10:00+00:00"),
        _d("fox", "2026-05-01T01:40:00+00:00"),
        _d("deer", "2026-05-02T01:15:00+00:00"),
        _d("fox", "2026-05-02T01:50:00+00:00"),
        _d("turkey", "2026-05-01T13:00:00+00:00"),
    ]
    out = build_cooccurrence_report(rows, window_minutes=60)
    top = out["pairs"][0]
    assert {top["a"], top["b"]} == {"deer", "fox"}
    assert top["shared_windows"] == 2
    assert top["jaccard"] == 1.0  # deer and fox occupy exactly the same two windows
    assert out["strongest"]["jaccard"] == 1.0


def test_separate_windows_give_zero_shared_and_are_dropped():
    rows = [
        _d("deer", "2026-05-01T01:00:00+00:00"),
        _d("owl", "2026-05-01T05:00:00+00:00"),  # 4h apart → different 60-min windows
    ]
    out = build_cooccurrence_report(rows, window_minutes=60, min_shared=1)
    assert out["pairs"] == []  # no shared window → dropped


def test_activity_overlap_reflects_diel_alignment():
    # Two species both active at night → high overlap; a day species → low overlap.
    night = [_d("deer", f"2026-05-0{d}T0{h}:00:00+00:00") for d in range(1, 6) for h in (1, 2, 3)]
    night += [_d("fox", f"2026-05-0{d}T0{h}:30:00+00:00") for d in range(1, 6) for h in (1, 2, 3)]
    day = [_d("hawk", f"2026-05-0{d}T1{h}:00:00+00:00") for d in range(1, 6) for h in (2, 3, 4)]
    out = build_cooccurrence_report(night + day, window_minutes=60)
    pair = {(p["a"], p["b"]): p for p in out["pairs"]}
    df = pair.get(("deer", "fox")) or pair.get(("fox", "deer"))
    assert df is not None and df["activity_overlap"] >= 0.9  # aligned nocturnal timing
    # deer vs hawk (night vs day) — if present at all, must be low overlap.
    dh = pair.get(("deer", "hawk")) or pair.get(("hawk", "deer"))
    if dh is not None:
        assert dh["activity_overlap"] <= 0.1


def test_min_shared_filters_weak_pairs():
    rows = [
        _d("deer", "2026-05-01T01:10:00+00:00"),
        _d("fox", "2026-05-01T01:20:00+00:00"),   # 1 shared window
        _d("deer", "2026-05-02T01:00:00+00:00"),
        _d("fox", "2026-05-03T01:00:00+00:00"),
    ]
    assert build_cooccurrence_report(rows, min_shared=2)["pairs"] == []
    assert build_cooccurrence_report(rows, min_shared=1)["pairs"]
