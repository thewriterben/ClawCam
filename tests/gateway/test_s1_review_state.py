"""S1 (Remember): first-class human-review state on AI classifications.

DATA_MODEL.md requires every classification to carry a review state, and human
review must update review *metadata* on the original machine output rather than
deleting it. These tests cover the migration, defaulting, non-destructive
update, validation, and the triage query.
"""

from __future__ import annotations

import pytest

from clawcam_gateway.inference.detector import Detection, InferenceResult
from clawcam_gateway.storage.database import REVIEW_STATES, GatewayDatabase


def _db(tmp_path) -> GatewayDatabase:
    return GatewayDatabase(tmp_path / "g.db")


def _save(db: GatewayDatabase, event_id: str, label: str = "deer", conf: float = 0.9):
    result = InferenceResult(
        model_name="megadetector",
        model_version="5a",
        detections=[Detection(label, conf, [0.1, 0.1, 0.5, 0.5], label)],
    )
    db.save_inference_result(event_id, f"/media/{event_id}.jpg", result)
    return db.get_inference_result(event_id)


def test_new_classification_defaults_to_unreviewed(tmp_path) -> None:
    row = _save(_db(tmp_path), "evt-1")
    assert row["review_state"] == "unreviewed"
    assert row["reviewed_at"] is None and row["reviewer"] is None
    assert isinstance(row["result_id"], int)


def test_migration_is_idempotent(tmp_path) -> None:
    db = _db(tmp_path)
    _save(db, "evt-1")
    db.migrate()  # second run must not error or drop data
    db.migrate()
    assert db.get_inference_result("evt-1")["review_state"] == "unreviewed"


def test_set_review_state_updates_metadata_nondestructively(tmp_path) -> None:
    db = _db(tmp_path)
    original = _save(db, "evt-1", label="deer", conf=0.91)
    rid = original["result_id"]

    updated = db.set_review_state(rid, "verified", reviewer="ranger.kim", note="clear ID")
    assert updated["review_state"] == "verified"
    assert updated["reviewer"] == "ranger.kim"
    assert updated["review_note"] == "clear ID"
    assert updated["reviewed_at"] is not None
    # The raw machine detections are untouched — review never rewrites evidence.
    assert updated["detections"] == original["detections"]
    assert updated["top_label"] == "deer"
    # Persisted, not just returned.
    assert db.get_inference_result("evt-1")["review_state"] == "verified"


def test_set_review_state_rejects_invalid_state(tmp_path) -> None:
    db = _db(tmp_path)
    rid = _save(db, "evt-1")["result_id"]
    with pytest.raises(ValueError):
        db.set_review_state(rid, "definitely-a-bear")


def test_set_review_state_unknown_result_returns_none(tmp_path) -> None:
    assert _db(tmp_path).set_review_state(999_999, "verified") is None


def test_save_rejects_invalid_review_state(tmp_path) -> None:
    class _BadResult:
        def to_dict(self):
            return {
                "model_name": "m", "model_version": "1",
                "detections": [], "top_label": None,
                "top_confidence": 0.0, "top_species": None,
                "review_state": "bogus",
            }

    with pytest.raises(ValueError):
        _db(tmp_path).save_inference_result("evt-x", "/m.jpg", _BadResult())


def test_list_by_review_state_filters_and_validates(tmp_path) -> None:
    db = _db(tmp_path)
    for i in range(3):
        _save(db, f"evt-{i}")
    # Flag one for review.
    rid = db.get_inference_result("evt-1")["result_id"]
    db.set_review_state(rid, "needs_review", reviewer="auto-qa")

    unreviewed = db.list_inference_results_by_review_state("unreviewed")
    needs = db.list_inference_results_by_review_state("needs_review")
    assert {r["event_id"] for r in unreviewed} == {"evt-0", "evt-2"}
    assert [r["event_id"] for r in needs] == ["evt-1"]
    with pytest.raises(ValueError):
        db.list_inference_results_by_review_state("nope")


def test_all_review_states_accepted(tmp_path) -> None:
    db = _db(tmp_path)
    rid = _save(db, "evt-1")["result_id"]
    for state in REVIEW_STATES:
        assert db.set_review_state(rid, state)["review_state"] == state
