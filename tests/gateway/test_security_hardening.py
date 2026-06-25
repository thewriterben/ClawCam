"""Regression tests for the Phase 13 security hardening pass.

Covers the SSRF guard on webhook delivery, the upload filename/path-traversal
sanitization, and the upload size caps.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from clawcam_gateway.alerts.webhook import deliver_webhook
from clawcam_gateway.api.app import (
    MAX_FIRMWARE_BYTES,
    _safe_path_component,
    _safe_suffix,
    create_app,
)
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.storage.database import GatewayDatabase


# ── SSRF guard ──────────────────────────────────────────────────────────────

class TestWebhookSSRFGuard:
    def test_loopback_blocked_by_default(self):
        ok, status, err = deliver_webhook("http://127.0.0.1/hook", {"x": 1})
        assert ok is False and status is None
        assert err.startswith("blocked")

    def test_localhost_name_blocked(self):
        ok, _, err = deliver_webhook("http://localhost:8080/hook", {"x": 1})
        assert ok is False and err.startswith("blocked")

    def test_cloud_metadata_blocked(self):
        ok, _, err = deliver_webhook("http://169.254.169.254/latest/meta-data/", {"x": 1})
        assert ok is False and err.startswith("blocked")

    def test_private_rfc1918_blocked(self):
        ok, _, err = deliver_webhook("http://10.0.0.5/hook", {"x": 1})
        assert ok is False and err.startswith("blocked")

    def test_non_http_scheme_blocked(self):
        ok, _, err = deliver_webhook("file:///etc/passwd", {"x": 1})
        assert ok is False and "scheme" in err

    def test_allow_private_bypasses_guard(self):
        # With allow_private the guard is skipped; the call is attempted and
        # fails on connection (not "blocked"), proving the guard was bypassed.
        ok, _, err = deliver_webhook("http://127.0.0.1:1/", {"x": 1}, timeout=1, allow_private=True)
        assert ok is False
        assert not (err or "").startswith("blocked")


# ── Filename / path-component helpers ────────────────────────────────────────

class TestPathSafety:
    def test_safe_component_accepts_normal_ids(self):
        assert _safe_path_component("evt-node-001-20260512")
        assert _safe_path_component("cap_123.jpg")

    def test_safe_component_rejects_traversal(self):
        assert not _safe_path_component("../etc/passwd")
        assert not _safe_path_component("a/b")
        assert not _safe_path_component("a\\b")
        assert not _safe_path_component("..")

    def test_safe_suffix_allowlist(self):
        assert _safe_suffix("x.PNG", (".jpg", ".png"), ".jpg") == ".png"
        assert _safe_suffix("x.exe", (".jpg", ".png"), ".jpg") == ".jpg"
        assert _safe_suffix(None, (".wav",), ".wav") == ".wav"


# ── Upload endpoint hardening ─────────────────────────────────────────────────

def _client(tmp_path):
    db_path = tmp_path / "gateway.db"
    GatewayDatabase(db_path)
    app = create_app(GatewayConfig(database_path=db_path, media_dir=tmp_path / "media"))
    return TestClient(app), tmp_path / "media"


def test_media_upload_rejects_traversal_event_id(tmp_path):
    client, _ = _client(tmp_path)
    # A traversal id that survives routing (no slashes) is still rejected.
    # "evt..x" contains a ".." traversal marker but no slash, so it reaches the
    # handler (the client does not normalize it) and is rejected by the guard.
    resp = client.post("/api/v1/media/evt..x", files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert resp.status_code == 400


def test_firmware_upload_sanitizes_traversal_filename(tmp_path):
    client, media = _client(tmp_path)
    resp = client.post(
        "/api/v1/firmware",
        files={"file": ("../../../../tmp/evil.bin", b"\x00\x01\x02", "application/octet-stream")},
    )
    assert resp.status_code == 200
    # Nothing escaped the firmware dir; the stored name has no traversal.
    fw_dir = media / "firmware"
    stored = list(fw_dir.glob("*"))
    assert stored, "firmware file should be stored inside the firmware dir"
    for p in stored:
        assert ".." not in p.name
        assert p.resolve().parent == fw_dir.resolve()
    # And no file leaked to a parent location.
    assert not (media.parent / "evil.bin").exists()


def test_firmware_upload_rejects_oversize(tmp_path):
    client, _ = _client(tmp_path)
    big = b"\x00" * (MAX_FIRMWARE_BYTES + 1)
    resp = client.post(
        "/api/v1/firmware",
        files={"file": ("big.bin", big, "application/octet-stream")},
    )
    assert resp.status_code == 413
