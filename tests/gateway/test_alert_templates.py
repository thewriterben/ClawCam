"""Per-profile alert-rule templates + the seed/preview tools."""

from __future__ import annotations

from clawcam_gateway.alerts.templates import alert_rule_templates_for_profile
from clawcam_gateway.storage.database import GatewayDatabase
from clawcam_gateway.tools import (
    ToolContext,
    apply_profile_alert_rules,
    list_profile_alert_templates,
)


# ── Template generator ───────────────────────────────────────────────────────

def test_livestock_templates_come_from_predator_metadata():
    templates = alert_rule_templates_for_profile("livestock_watch")
    assert len(templates) == 3
    patterns = {t["species_pattern"] for t in templates}
    assert patterns == {"coyote", "mountain lion", "wolf"}
    assert all(t["label"] == "animal" for t in templates)


def test_security_and_driveway_templates():
    outdoor = alert_rule_templates_for_profile("home_security_outdoor")
    assert {t["label"] for t in outdoor} == {"person", "vehicle"}

    indoor = alert_rule_templates_for_profile("home_security_indoor")
    assert {t["label"] for t in indoor} == {"person", "glass_break"}
    person = next(t for t in indoor if t["label"] == "person")
    assert person["required_state"] == "armed"

    driveway = alert_rule_templates_for_profile("driveway")
    assert {t["label"] for t in driveway} == {"person", "vehicle"}


def test_garden_and_wildlife_templates():
    assert alert_rule_templates_for_profile("garden")[0]["label"] == "animal"
    assert alert_rule_templates_for_profile("wildlife_trail_camera")[0]["label"] == "person"


def test_passive_profiles_have_no_templates():
    for profile in ("general", "bird_feeder", "hummingbird_feeder", "apiary"):
        assert alert_rule_templates_for_profile(profile) == []


# ── Tools ────────────────────────────────────────────────────────────────────

def _ctx(tmp_path):
    return ToolContext(database_path=tmp_path / "g.db")


def _seed_device(db: GatewayDatabase, device_id: str, profile: str):
    db.upsert_device({
        "device_id": device_id, "device_type": "node", "name": device_id,
        "status": "active", "created_at": "2026-05-12T00:00:00Z",
    })
    db.set_device_profile(device_id, profile)


def test_list_tool_preview(tmp_path):
    ctx = _ctx(tmp_path)
    ok = list_profile_alert_templates(ctx, profile="livestock_watch")
    assert ok["ok"] is True and ok["count"] == 3
    bad = list_profile_alert_templates(ctx, profile="not_a_profile")
    assert bad["ok"] is False


def test_apply_tool_seeds_rules_for_device(tmp_path):
    ctx = _ctx(tmp_path)
    _seed_device(ctx.db, "cam-live", "livestock_watch")
    result = apply_profile_alert_rules(ctx, device_id="cam-live")
    assert result["ok"] is True
    assert result["profile"] == "livestock_watch"
    assert result["created_count"] == 3

    rules = ctx.db.list_alert_rules()
    seeded = [r for r in rules if r["device_id"] == "cam-live"]
    assert len(seeded) == 3
    assert all(r["label"] == "animal" for r in seeded)


def test_apply_tool_unknown_device(tmp_path):
    result = apply_profile_alert_rules(_ctx(tmp_path), device_id="ghost")
    assert result["ok"] is False
    assert "unknown device" in result["error"]


def test_apply_tool_passive_profile_creates_none(tmp_path):
    ctx = _ctx(tmp_path)
    _seed_device(ctx.db, "cam-feeder", "bird_feeder")
    result = apply_profile_alert_rules(ctx, device_id="cam-feeder")
    assert result["ok"] is True
    assert result["created_count"] == 0
