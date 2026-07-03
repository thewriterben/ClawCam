"""Periodic alert digest tests — pure roll-up, the ``since`` window query, and the
scheduler ``alert_digest`` action. Completes the Oh-Ben-Claw notification mirror.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
if str(_GW) not in sys.path:
    sys.path.insert(0, str(_GW))

from clawcam_gateway.alerts.digest import build_alert_digest
from clawcam_gateway.scheduler.engine import ScheduleEngine
from clawcam_gateway.storage.database import GatewayDatabase


def _events() -> list[dict]:
    return [
        {"rule_name": "deer", "top_species": "Odocoileus virginianus", "top_label": "animal",
         "delivery_status": "delivered", "suppressed_count": 4},
        {"rule_name": "deer", "top_species": "Odocoileus virginianus", "top_label": "animal",
         "delivery_status": "delivered", "suppressed_count": 0},
        {"rule_name": "intruder", "top_species": "", "top_label": "person",
         "delivery_status": "skipped_severity", "suppressed_count": 0},
    ]


def test_build_digest_groups_and_totals():
    d = build_alert_digest(_events(), window_label="24h")
    assert d["window"] == "24h"
    assert d["total_alerts"] == 3
    assert d["suppressed_total"] == 4
    assert d["delivered"] == 2
    assert d["skipped_by_severity"] == 1
    assert d["by_rule"][0] == {"name": "deer", "count": 2}  # most frequent first
    by_species = {r["name"]: r["count"] for r in d["by_species"]}
    assert by_species["Odocoileus virginianus"] == 2
    assert by_species["person"] == 1  # top_label fallback when species empty


def test_empty_digest():
    d = build_alert_digest([], "24h")
    assert d["total_alerts"] == 0
    assert d["by_rule"] == []
    assert d["by_species"] == []


def _seed(db: GatewayDatabase, n_recent: int = 3, n_old: int = 1) -> None:
    now = datetime.now(timezone.utc)
    for i in range(n_recent):
        db.add_alert_event({
            "alert_event_id": f"a-recent-{i}", "rule_id": "r1", "rule_name": "deer",
            "event_id": None, "device_id": "d1", "top_label": "animal",
            "top_confidence": 0.9, "top_species": "Odocoileus virginianus",
            "webhook_url": None, "delivery_status": "delivered",
            "webhook_response": "200", "fired_at": now.isoformat(),
            "severity": "warning", "suppressed_count": i,
        })
    old = (now - timedelta(days=7)).isoformat()
    for i in range(n_old):
        db.add_alert_event({
            "alert_event_id": f"a-old-{i}", "rule_id": "r1", "rule_name": "deer",
            "event_id": None, "device_id": "d1", "top_label": "animal",
            "top_confidence": 0.9, "top_species": "Odocoileus virginianus",
            "webhook_url": None, "delivery_status": "delivered",
            "webhook_response": "200", "fired_at": old,
            "severity": "warning", "suppressed_count": 0,
        })


def test_list_alert_events_since_window(tmp_path):
    db = GatewayDatabase(tmp_path / "d.db")
    _seed(db, n_recent=3, n_old=1)
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    recent = db.list_alert_events(limit=100, since=since)
    assert len(recent) == 3, "the 7-day-old event is outside the window"


def test_scheduler_alert_digest_action_posts_the_rollup(tmp_path):
    db = GatewayDatabase(tmp_path / "d.db")
    _seed(db, n_recent=3, n_old=1)
    captured: dict = {}

    def fake_deliver(url, body):
        captured["url"] = url
        captured["body"] = body
        return (True, 200, None)

    engine = ScheduleEngine(db=db, webhook_deliverer=fake_deliver)
    res = engine._action_alert_digest("sched-1", {"url": "http://hook", "window_s": 3600})

    assert res.status == "success"
    assert captured["url"] == "http://hook"
    assert captured["body"]["total_alerts"] == 3  # only the recent events
    assert captured["body"]["suppressed_total"] == 0 + 1 + 2


def test_scheduler_alert_digest_requires_url(tmp_path):
    db = GatewayDatabase(tmp_path / "d.db")
    engine = ScheduleEngine(db=db, webhook_deliverer=lambda u, b: (True, 200, None))
    res = engine._action_alert_digest("sched-1", {"window_s": 3600})
    assert res.status == "failed"
