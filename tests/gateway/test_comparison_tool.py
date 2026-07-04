"""Tool-level test for get_comparison_report — verifies the current/previous window split.

Uses a stub ToolContext.db so no real database is needed. The window boundaries are
computed from ``datetime.now(UTC)``, so detections are dated relative to now.
"""

from datetime import datetime, timedelta, timezone

from clawcam_gateway.tools.clawcam_tools import get_comparison_report


class _StubDB:
    def __init__(self, rows):
        self._rows = rows

    def list_inference_results(self, limit=25, min_confidence=0.0, deployment_id=None, **kw):
        return list(self._rows)


class _Ctx:
    def __init__(self, rows):
        self.db = _StubDB(rows)


def _row(species, ran_at):
    return {"top_species": species, "top_label": species, "top_confidence": 0.9, "ran_at": ran_at}


def test_window_split_current_vs_previous():
    now = datetime.now(timezone.utc)
    iso = lambda days_ago: (now - timedelta(days=days_ago)).isoformat()
    rows = [
        _row("deer", iso(1)),   # current window (last 7d)
        _row("deer", iso(3)),   # current
        _row("fox", iso(10)),   # previous window (7–14d ago)
        _row("bear", iso(20)),  # older than both windows — excluded
    ]
    out = get_comparison_report(_Ctx(rows), window_days=7)
    assert out["ok"] is True
    rep = out["report"]
    assert rep["total_current"] == 2      # two deer in last 7d
    assert rep["total_previous"] == 1     # one fox in prior 7d
    assert rep["new_subjects"] == ["deer"]
    assert rep["dropped_subjects"] == ["fox"]
    assert rep["current_label"] == "last 7d"
    assert rep["previous_label"] == "prior 7d"
