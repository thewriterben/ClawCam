"""Tests for the scheduler ``daily_summary`` action.

Uses a stub DB and stub webhook deliverer — the engine injects both — so this exercises
the action end-to-end without a real database or network.
"""

from clawcam_gateway.scheduler.actions import ACTION_DAILY_SUMMARY
from clawcam_gateway.scheduler.engine import ScheduleEngine


class StubDB:
    def __init__(self, detections, alerts):
        self._dets = detections
        self._alerts = alerts

    def list_inference_results(self, limit=25, deployment_id=None, **kw):
        return list(self._dets)

    def list_alert_events(self, limit=25, deployment_id=None, since=None, **kw):
        return list(self._alerts)


def _det(species, ran_at):
    return {"top_species": species, "top_label": species, "top_confidence": 0.9, "ran_at": ran_at}


def test_daily_summary_action_delivers_site_report():
    dets = [_det("deer", "2026-07-01T22:00:00"), _det("fox", "2026-07-01T02:00:00")]
    captured = {}

    def webhook(url, body):
        captured["url"] = url
        captured["body"] = body
        return (True, 200, None)

    eng = ScheduleEngine(StubDB(dets, []), webhook_deliverer=webhook)
    res = eng._dispatch(
        {
            "schedule_id": "s1",
            "action_type": ACTION_DAILY_SUMMARY,
            "action_payload": {"url": "http://hook", "report_date": "2026-07-01"},
        }
    )
    assert res.status == "success"
    assert captured["url"] == "http://hook"
    body = captured["body"]
    assert body["date"] == "2026-07-01"
    assert body["site"]["headline"]["total_detections"] == 2
    assert body["site"]["headline"]["distinct_subjects"] == 2
    assert "2 detections" in body["detection_summary"]
    assert res.detail["total_detections"] == 2


def test_daily_summary_action_filters_to_report_date():
    dets = [_det("deer", "2026-07-01T22:00:00"), _det("bear", "2026-06-30T10:00:00")]
    captured = {}
    eng = ScheduleEngine(
        StubDB(dets, []),
        webhook_deliverer=lambda u, b: (captured.setdefault("body", b), (True, 200, None))[1],
    )
    res = eng._dispatch(
        {
            "schedule_id": "s2",
            "action_type": ACTION_DAILY_SUMMARY,
            "action_payload": {"url": "http://hook", "report_date": "2026-07-01"},
        }
    )
    assert res.status == "success"
    # Only the 2026-07-01 detection counts; the 06-30 bear is filtered out.
    assert captured["body"]["site"]["headline"]["total_detections"] == 1


def test_daily_summary_requires_url():
    eng = ScheduleEngine(StubDB([], []), webhook_deliverer=lambda u, b: (True, 200, None))
    res = eng._dispatch(
        {"schedule_id": "s3", "action_type": ACTION_DAILY_SUMMARY, "action_payload": {}}
    )
    assert res.status == "failed"
    assert "url" in (res.error or "")
