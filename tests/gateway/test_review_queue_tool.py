"""Tool-level test for get_review_queue — stub DB, no real database needed."""

from clawcam_gateway.tools.clawcam_tools import get_review_queue


class _StubDB:
    def __init__(self, rows):
        self._rows = rows

    def list_inference_results_by_review_state(self, review_state, limit=25):
        assert review_state == "unreviewed"
        return list(self._rows)[:limit]


class _Ctx:
    def __init__(self, rows):
        self.db = _StubDB(rows)


def _row(rid, label, conf, species=None):
    return {"result_id": rid, "event_id": rid, "top_label": label,
            "top_confidence": conf, "top_species": species}


def test_review_queue_ranks_and_counts():
    rows = [
        _row("a", "animal", 0.98, species="deer"),   # low
        _row("b", "animal", 0.5, species="fox"),     # high
        _row("c", "animal", 0.9, species=None),      # medium
    ]
    out = get_review_queue(_Ctx(rows), limit=50)
    assert out["ok"] is True
    q = out["queue"]
    assert q["counts"] == {"high": 1, "medium": 1, "low": 1}
    assert q["needs_review"] == 2
    assert q["items"][0]["result_id"] == "b"  # highest priority first


def test_rare_species_is_honored():
    rows = [_row("a", "animal", 0.97, species="mountain lion")]
    out = get_review_queue(_Ctx(rows), rare_species=["mountain lion"])
    item = out["queue"]["items"][0]
    assert item["priority"] == "medium"
    assert any("rare species" in r for r in item["reasons"])
