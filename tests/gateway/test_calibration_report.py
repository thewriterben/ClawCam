"""Tests for confidence calibration from review labels (pure, import-isolated)."""

from clawcam_gateway.analytics.calibration import build_calibration_report


def _row(conf, state):
    return {"top_confidence": conf, "review_state": state}


def test_no_reviewed_rows():
    r = build_calibration_report([_row(0.9, "unreviewed"), _row(0.5, "needs_review")])
    assert r["reviewed"] == 0
    assert r["suggested_threshold"] is None
    assert "no reviewed" in r["message"]


def test_counts_positives_and_negatives():
    rows = [
        _row(0.95, "verified"),
        _row(0.90, "corrected"),   # also a positive
        _row(0.30, "rejected"),
        _row(0.80, "unreviewed"),  # ignored
    ]
    r = build_calibration_report(rows)
    assert r["reviewed"] == 3
    assert r["confirmed"] == 2
    assert r["rejected"] == 1
    assert r["overall_precision"] == round(2 / 3, 3)


def test_well_calibrated_when_confidence_tracks_correctness():
    # Low confidence → rejected, high confidence → verified.
    rows = [_row(0.1, "rejected"), _row(0.2, "rejected"),
            _row(0.85, "verified"), _row(0.95, "verified")]
    r = build_calibration_report(rows, buckets=10)
    assert r["well_calibrated"] is True


def test_not_well_calibrated_when_high_conf_is_wrong():
    rows = [_row(0.1, "verified"), _row(0.95, "rejected")]
    r = build_calibration_report(rows, buckets=10)
    assert r["well_calibrated"] is False


def test_suggested_threshold_meets_target_precision():
    # 3 correct high-confidence + 1 wrong low-confidence.
    rows = [
        _row(0.95, "verified"),
        _row(0.90, "verified"),
        _row(0.85, "corrected"),
        _row(0.40, "rejected"),
    ]
    r = build_calibration_report(rows, target_precision=0.9)
    # Accepting >= 0.85 gives 3/3 = 1.0 precision → threshold 0.85, all 3 accepted.
    assert r["suggested_threshold"] == 0.85
    assert r["accepted_at_threshold"] == 3
    assert r["precision_at_threshold"] == 1.0


def test_no_threshold_when_top_is_false_positive():
    rows = [_row(0.99, "rejected"), _row(0.5, "verified")]
    r = build_calibration_report(rows, target_precision=0.9)
    # Top detection is wrong → no prefix reaches 0.9 precision.
    assert r["suggested_threshold"] is None


def test_buckets_partition_confidence():
    rows = [_row(0.05, "rejected"), _row(0.95, "verified")]
    r = build_calibration_report(rows, buckets=10)
    assert len(r["buckets"]) == 10
    assert r["buckets"][0]["rejected"] == 1
    assert r["buckets"][9]["confirmed"] == 1
    assert r["buckets"][0]["confirmed_rate"] == 0.0
    assert r["buckets"][9]["confirmed_rate"] == 1.0
