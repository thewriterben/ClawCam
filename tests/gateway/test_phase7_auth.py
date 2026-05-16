"""Phase 7 tests: deployments + API key auth + scope enforcement.

Coverage
--------
- Token generation: shape, uniqueness, hash determinism, redaction
- Scope hierarchy: admin > write > read; ``scope_satisfies`` correctness
- ``AuthContext.require`` raises ``ScopeRequired`` when insufficient
- DB CRUD: deployments (add/get/list/update/delete with default protection),
  api_keys (add/get_by_hash/get/list/touch/revoke/delete)
- REST endpoints (auth disabled): default deployment exists, full CRUD
- REST endpoints (auth enabled): 401 without key, 403 on scope mismatch,
  successful flow with admin key, cross-deployment isolation
- Backward compat: ``auth_enabled=False`` keeps every existing endpoint
  working without an Authorization header (smoke-test against /api/v1/devices)
- Migration: legacy tables get deployment_id column with 'default' value
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[2]
_GW = _REPO / "gateway"
_BRAIN_DIR = _REPO / "brain" / "oh-ben-claw-adapter"
for _p in (_GW, _BRAIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient

from clawcam_gateway.api.app import create_app
from clawcam_gateway.auth import (
    AuthContext,
    SCOPE_ADMIN,
    SCOPE_READ,
    SCOPE_WRITE,
    ScopeRequired,
    generate_api_key,
    hash_api_key,
    redact_key,
    scope_satisfies,
    synthetic_admin_context,
)
from clawcam_gateway.config import GatewayConfig
from clawcam_gateway.storage.database import GatewayDatabase


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path) -> GatewayDatabase:
    return GatewayDatabase(tmp_path / "test.db")


def _make_client(tmp_path: Path, auth_enabled: bool = False) -> tuple[TestClient, GatewayDatabase]:
    db_path = tmp_path / "test.db"
    cfg = GatewayConfig(
        database_path=db_path,
        media_dir=tmp_path / "media",
        auth_enabled=auth_enabled,
    )
    app = create_app(config=cfg)
    return TestClient(app), GatewayDatabase(db_path)


@pytest.fixture()
def client_no_auth(tmp_path: Path) -> tuple[TestClient, GatewayDatabase]:
    return _make_client(tmp_path, auth_enabled=False)


@pytest.fixture()
def client_auth(tmp_path: Path) -> tuple[TestClient, GatewayDatabase]:
    client, db = _make_client(tmp_path, auth_enabled=True)
    return client, db


# ── Token primitives ──────────────────────────────────────────────────────────

class TestTokenPrimitives:
    def test_generate_returns_prefixed_string(self):
        tok = generate_api_key()
        assert tok.startswith("cc_")
        # 32 raw bytes -> 43 url-safe base64 chars + 3 prefix chars = 46 total
        assert len(tok) >= 40

    def test_generate_is_unique(self):
        tokens = {generate_api_key() for _ in range(20)}
        assert len(tokens) == 20

    def test_hash_is_deterministic(self):
        assert hash_api_key("foo") == hash_api_key("foo")
        assert hash_api_key("foo") != hash_api_key("bar")

    def test_hash_length_is_64(self):
        assert len(hash_api_key("anything")) == 64

    def test_redact_shows_last_four_only(self):
        assert redact_key("cc_supersecrettokenABCD").endswith("ABCD")
        assert "supersecret" not in redact_key("cc_supersecrettokenABCD")


# ── Scope hierarchy ──────────────────────────────────────────────────────────

class TestScopeHierarchy:
    def test_admin_satisfies_all(self):
        assert scope_satisfies(SCOPE_ADMIN, SCOPE_READ)
        assert scope_satisfies(SCOPE_ADMIN, SCOPE_WRITE)
        assert scope_satisfies(SCOPE_ADMIN, SCOPE_ADMIN)

    def test_write_satisfies_read_but_not_admin(self):
        assert scope_satisfies(SCOPE_WRITE, SCOPE_READ)
        assert scope_satisfies(SCOPE_WRITE, SCOPE_WRITE)
        assert not scope_satisfies(SCOPE_WRITE, SCOPE_ADMIN)

    def test_read_satisfies_only_read(self):
        assert scope_satisfies(SCOPE_READ, SCOPE_READ)
        assert not scope_satisfies(SCOPE_READ, SCOPE_WRITE)
        assert not scope_satisfies(SCOPE_READ, SCOPE_ADMIN)

    def test_unknown_scope_satisfies_nothing(self):
        assert not scope_satisfies("nonsense", SCOPE_READ)

    def test_auth_context_require_raises(self):
        ctx = AuthContext(deployment_id="d1", scope=SCOPE_READ)
        with pytest.raises(ScopeRequired):
            ctx.require(SCOPE_WRITE)

    def test_auth_context_require_passes(self):
        ctx = AuthContext(deployment_id="d1", scope=SCOPE_ADMIN)
        ctx.require(SCOPE_WRITE)  # no exception

    def test_synthetic_admin_context(self):
        ctx = synthetic_admin_context()
        assert ctx.scope == SCOPE_ADMIN
        assert ctx.deployment_id == "default"
        assert ctx.authenticated is False


# ── Database: deployments ─────────────────────────────────────────────────────

class TestDeploymentsDB:
    def test_default_deployment_is_seeded(self, tmp_db: GatewayDatabase):
        d = tmp_db.get_deployment("default")
        assert d is not None
        assert d["deployment_id"] == "default"
        assert d["profile"] == "general"

    def test_add_and_get_deployment(self, tmp_db: GatewayDatabase):
        tmp_db.add_deployment({
            "deployment_id": "dep-test-1",
            "name": "Test Dep",
            "profile": "home_security",
            "metadata": {"location": "main_house"},
        })
        d = tmp_db.get_deployment("dep-test-1")
        assert d is not None
        assert d["name"] == "Test Dep"
        assert d["profile"] == "home_security"
        assert d["metadata"] == {"location": "main_house"}

    def test_get_unknown_returns_none(self, tmp_db: GatewayDatabase):
        assert tmp_db.get_deployment("nonexistent") is None

    def test_list_includes_default(self, tmp_db: GatewayDatabase):
        ids = {d["deployment_id"] for d in tmp_db.list_deployments()}
        assert "default" in ids

    def test_list_filter_by_status(self, tmp_db: GatewayDatabase):
        tmp_db.add_deployment({"deployment_id": "dep-archived", "name": "Archived", "status": "archived"})
        active = tmp_db.list_deployments(status="active")
        archived = tmp_db.list_deployments(status="archived")
        assert all(d["status"] == "active" for d in active)
        assert any(d["deployment_id"] == "dep-archived" for d in archived)

    def test_update_deployment(self, tmp_db: GatewayDatabase):
        tmp_db.add_deployment({"deployment_id": "dep-upd", "name": "old"})
        ok = tmp_db.update_deployment("dep-upd", {"name": "new", "status": "archived"})
        assert ok
        d = tmp_db.get_deployment("dep-upd")
        assert d["name"] == "new"
        assert d["status"] == "archived"

    def test_update_unknown_returns_false(self, tmp_db: GatewayDatabase):
        assert not tmp_db.update_deployment("nonexistent", {"name": "x"})

    def test_delete_deployment(self, tmp_db: GatewayDatabase):
        tmp_db.add_deployment({"deployment_id": "dep-del", "name": "to delete"})
        assert tmp_db.delete_deployment("dep-del")
        assert tmp_db.get_deployment("dep-del") is None

    def test_cannot_delete_default(self, tmp_db: GatewayDatabase):
        assert not tmp_db.delete_deployment("default")
        assert tmp_db.get_deployment("default") is not None


# ── Database: api_keys ────────────────────────────────────────────────────────

class TestApiKeysDB:
    def test_add_and_lookup_by_hash(self, tmp_db: GatewayDatabase):
        token = generate_api_key()
        tmp_db.add_api_key({
            "key_id": "key-test-1",
            "deployment_id": "default",
            "name": "test key",
            "key_hash": hash_api_key(token),
            "scope": "admin",
        })
        record = tmp_db.get_api_key_by_hash(hash_api_key(token))
        assert record is not None
        assert record["key_id"] == "key-test-1"
        assert record["scope"] == "admin"
        assert record["enabled"] is True

    def test_lookup_by_unknown_hash_returns_none(self, tmp_db: GatewayDatabase):
        assert tmp_db.get_api_key_by_hash("aa" * 32) is None

    def test_list_filter_by_deployment(self, tmp_db: GatewayDatabase):
        tmp_db.add_deployment({"deployment_id": "dep-keys", "name": "keys"})
        tmp_db.add_api_key({"key_id": "k-default", "deployment_id": "default",
                            "name": "d", "key_hash": "h1", "scope": "read"})
        tmp_db.add_api_key({"key_id": "k-other", "deployment_id": "dep-keys",
                            "name": "o", "key_hash": "h2", "scope": "read"})
        default_keys = tmp_db.list_api_keys(deployment_id="default")
        assert len(default_keys) == 1
        assert default_keys[0]["key_id"] == "k-default"

    def test_revoke_sets_enabled_false(self, tmp_db: GatewayDatabase):
        tmp_db.add_api_key({"key_id": "k-rev", "deployment_id": "default",
                            "name": "r", "key_hash": "h3", "scope": "read"})
        assert tmp_db.revoke_api_key("k-rev")
        record = tmp_db.get_api_key("k-rev")
        assert record["enabled"] is False

    def test_touch_updates_last_used(self, tmp_db: GatewayDatabase):
        tmp_db.add_api_key({"key_id": "k-touch", "deployment_id": "default",
                            "name": "t", "key_hash": "h4", "scope": "read"})
        before = tmp_db.get_api_key("k-touch")
        assert before["last_used_at"] is None
        tmp_db.touch_api_key("k-touch")
        after = tmp_db.get_api_key("k-touch")
        assert after["last_used_at"] is not None

    def test_delete_removes_row(self, tmp_db: GatewayDatabase):
        tmp_db.add_api_key({"key_id": "k-del", "deployment_id": "default",
                            "name": "d", "key_hash": "h5", "scope": "read"})
        assert tmp_db.delete_api_key("k-del")
        assert tmp_db.get_api_key("k-del") is None


# ── Migration: deployment_id column added to legacy tables ────────────────────

class TestMigration:
    def test_devices_has_deployment_id_column(self, tmp_db: GatewayDatabase):
        with tmp_db.connect() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(devices)").fetchall()}
        assert "deployment_id" in cols

    def test_events_has_deployment_id_column(self, tmp_db: GatewayDatabase):
        with tmp_db.connect() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        assert "deployment_id" in cols

    def test_alert_rules_has_deployment_id_column(self, tmp_db: GatewayDatabase):
        with tmp_db.connect() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(alert_rules)").fetchall()}
        assert "deployment_id" in cols

    def test_migration_is_idempotent(self, tmp_path: Path):
        # Creating twice on the same path must not raise.
        db1 = GatewayDatabase(tmp_path / "idempotent.db")
        db2 = GatewayDatabase(tmp_path / "idempotent.db")
        assert db1.get_deployment("default") is not None
        assert db2.get_deployment("default") is not None


# ── REST endpoints (auth DISABLED) ────────────────────────────────────────────

class TestDeploymentsRESTNoAuth:
    def test_health_reports_auth_disabled(self, client_no_auth):
        client, _ = client_no_auth
        body = client.get("/health").json()
        assert body["auth_enabled"] is False

    def test_list_deployments_includes_default(self, client_no_auth):
        client, _ = client_no_auth
        resp = client.get("/api/v1/deployments")
        assert resp.status_code == 200
        ids = {d["deployment_id"] for d in resp.json()["deployments"]}
        assert "default" in ids

    def test_create_deployment(self, client_no_auth):
        client, _ = client_no_auth
        resp = client.post("/api/v1/deployments", json={
            "data": {"name": "Backyard Bird Feeder", "profile": "bird_feeder"},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["deployment"]["profile"] == "bird_feeder"

    def test_create_missing_name_400(self, client_no_auth):
        client, _ = client_no_auth
        resp = client.post("/api/v1/deployments", json={"data": {}})
        assert resp.status_code == 400

    def test_create_explicit_id_conflict_409(self, client_no_auth):
        client, _ = client_no_auth
        client.post("/api/v1/deployments", json={
            "data": {"deployment_id": "dep-fixed", "name": "first"},
        })
        resp = client.post("/api/v1/deployments", json={
            "data": {"deployment_id": "dep-fixed", "name": "second"},
        })
        assert resp.status_code == 409

    def test_get_unknown_404(self, client_no_auth):
        client, _ = client_no_auth
        assert client.get("/api/v1/deployments/nope").status_code == 404

    def test_patch_deployment(self, client_no_auth):
        client, _ = client_no_auth
        create = client.post("/api/v1/deployments", json={"data": {"name": "patch test"}}).json()
        dep_id = create["deployment"]["deployment_id"]
        resp = client.patch(f"/api/v1/deployments/{dep_id}",
                            json={"data": {"name": "renamed"}})
        assert resp.status_code == 200
        assert resp.json()["deployment"]["name"] == "renamed"

    def test_delete_default_refused(self, client_no_auth):
        client, _ = client_no_auth
        assert client.delete("/api/v1/deployments/default").status_code == 400

    def test_delete_custom_deployment(self, client_no_auth):
        client, _ = client_no_auth
        create = client.post("/api/v1/deployments", json={"data": {"name": "delete me"}}).json()
        dep_id = create["deployment"]["deployment_id"]
        assert client.delete(f"/api/v1/deployments/{dep_id}").status_code == 200
        assert client.get(f"/api/v1/deployments/{dep_id}").status_code == 404


class TestApiKeysRESTNoAuth:
    def test_create_returns_token_once(self, client_no_auth):
        client, db = client_no_auth
        resp = client.post("/api/v1/api-keys", json={
            "data": {"name": "test key", "scope": "write"},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["token"].startswith("cc_")
        assert "warning" in body
        # Verify hash actually persisted
        record = db.get_api_key_by_hash(hash_api_key(body["token"]))
        assert record is not None
        assert record["scope"] == "write"

    def test_create_missing_name_400(self, client_no_auth):
        client, _ = client_no_auth
        assert client.post("/api/v1/api-keys", json={"data": {}}).status_code == 400

    def test_create_invalid_scope_400(self, client_no_auth):
        client, _ = client_no_auth
        resp = client.post("/api/v1/api-keys", json={
            "data": {"name": "x", "scope": "superuser"},
        })
        assert resp.status_code == 400

    def test_create_unknown_deployment_404(self, client_no_auth):
        client, _ = client_no_auth
        resp = client.post("/api/v1/api-keys", json={
            "data": {"name": "x", "deployment_id": "does-not-exist"},
        })
        assert resp.status_code == 404

    def test_list_does_not_reveal_token(self, client_no_auth):
        client, _ = client_no_auth
        client.post("/api/v1/api-keys", json={"data": {"name": "k1"}})
        body = client.get("/api/v1/api-keys").json()
        for key in body["keys"]:
            assert "token" not in key
            assert "key_hash" not in key

    def test_revoke_disables_key(self, client_no_auth):
        client, db = client_no_auth
        create = client.post("/api/v1/api-keys", json={"data": {"name": "rev"}}).json()
        key_id = create["key_id"]
        assert client.post(f"/api/v1/api-keys/{key_id}/revoke").status_code == 200
        assert db.get_api_key(key_id)["enabled"] is False

    def test_delete_removes_key(self, client_no_auth):
        client, db = client_no_auth
        create = client.post("/api/v1/api-keys", json={"data": {"name": "del"}}).json()
        key_id = create["key_id"]
        assert client.delete(f"/api/v1/api-keys/{key_id}").status_code == 200
        assert db.get_api_key(key_id) is None


# ── REST endpoints (auth ENABLED) ─────────────────────────────────────────────

class TestAuthEnabled:
    def _bootstrap_admin_key(self, db: GatewayDatabase, deployment_id: str = "default") -> str:
        """Inject a known admin key directly to bootstrap (in production this would
        be a CLI tool or env-var-derived bootstrap key)."""
        token = generate_api_key()
        db.add_api_key({
            "key_id": "bootstrap-admin",
            "deployment_id": deployment_id,
            "name": "bootstrap",
            "key_hash": hash_api_key(token),
            "scope": "admin",
        })
        return token

    def _add_user_key(self, db: GatewayDatabase, scope: str, deployment_id: str = "default") -> str:
        token = generate_api_key()
        db.add_api_key({
            "key_id": f"user-{scope}",
            "deployment_id": deployment_id,
            "name": scope,
            "key_hash": hash_api_key(token),
            "scope": scope,
        })
        return token

    def test_health_reports_auth_enabled(self, client_auth):
        client, _ = client_auth
        body = client.get("/health").json()
        assert body["auth_enabled"] is True

    def test_health_unauthenticated_allowed(self, client_auth):
        """/health intentionally has no auth dependency."""
        client, _ = client_auth
        assert client.get("/health").status_code == 200

    def test_protected_endpoint_401_without_key(self, client_auth):
        client, _ = client_auth
        assert client.get("/api/v1/deployments").status_code == 401

    def test_protected_endpoint_401_with_wrong_key(self, client_auth):
        client, _ = client_auth
        resp = client.get("/api/v1/deployments",
                          headers={"Authorization": "Bearer cc_definitelynotvalid"})
        assert resp.status_code == 401

    def test_revoked_key_returns_403(self, client_auth):
        client, db = client_auth
        token = self._bootstrap_admin_key(db)
        db.revoke_api_key("bootstrap-admin")
        resp = client.get("/api/v1/deployments",
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_can_list_deployments(self, client_auth):
        client, db = client_auth
        token = self._bootstrap_admin_key(db)
        resp = client.get("/api/v1/deployments",
                          headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_x_api_key_header_also_works(self, client_auth):
        client, db = client_auth
        token = self._bootstrap_admin_key(db)
        resp = client.get("/api/v1/deployments", headers={"X-Api-Key": token})
        assert resp.status_code == 200

    def test_read_scope_cannot_create_deployment(self, client_auth):
        client, db = client_auth
        token = self._add_user_key(db, scope="read")
        resp = client.post("/api/v1/deployments",
                           json={"data": {"name": "blocked"}},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_write_scope_cannot_create_deployment(self, client_auth):
        """create_deployment is admin-only; write isn't enough."""
        client, db = client_auth
        token = self._add_user_key(db, scope="write")
        resp = client.post("/api/v1/deployments",
                           json={"data": {"name": "blocked"}},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_scope_can_create_deployment(self, client_auth):
        client, db = client_auth
        token = self._bootstrap_admin_key(db)
        resp = client.post("/api/v1/deployments",
                           json={"data": {"name": "new dep"}},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_non_admin_sees_only_own_deployment(self, client_auth):
        client, db = client_auth
        # admin creates two deployments + a read key against one of them
        admin_tok = self._bootstrap_admin_key(db)
        client.post("/api/v1/deployments", json={"data": {"deployment_id": "dep-a", "name": "A"}},
                    headers={"Authorization": f"Bearer {admin_tok}"})
        client.post("/api/v1/deployments", json={"data": {"deployment_id": "dep-b", "name": "B"}},
                    headers={"Authorization": f"Bearer {admin_tok}"})
        read_tok = self._add_user_key(db, scope="read", deployment_id="dep-a")
        body = client.get("/api/v1/deployments",
                          headers={"Authorization": f"Bearer {read_tok}"}).json()
        ids = {d["deployment_id"] for d in body["deployments"]}
        assert ids == {"dep-a"}

    def test_non_admin_cross_deployment_403(self, client_auth):
        client, db = client_auth
        admin_tok = self._bootstrap_admin_key(db)
        client.post("/api/v1/deployments", json={"data": {"deployment_id": "dep-x", "name": "X"}},
                    headers={"Authorization": f"Bearer {admin_tok}"})
        read_tok = self._add_user_key(db, scope="read", deployment_id="default")
        resp = client.get("/api/v1/deployments/dep-x",
                          headers={"Authorization": f"Bearer {read_tok}"})
        assert resp.status_code == 403

    def test_last_used_at_updated_on_request(self, client_auth):
        client, db = client_auth
        token = self._bootstrap_admin_key(db)
        assert db.get_api_key("bootstrap-admin")["last_used_at"] is None
        client.get("/api/v1/deployments", headers={"Authorization": f"Bearer {token}"})
        assert db.get_api_key("bootstrap-admin")["last_used_at"] is not None


# ── Backward compatibility ────────────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_existing_devices_endpoint_works_without_auth(self, client_no_auth):
        """When auth is disabled, /api/v1/devices should be open as before."""
        client, _ = client_no_auth
        # Register a device with the legacy payload shape (no deployment_id)
        client.post("/api/v1/devices", json={
            "data": {
                "device_id": "node-legacy-001",
                "device_type": "node",
                "name": "Legacy Node",
                "status": "active",
                "created_at": "2026-05-15T00:00:00Z",
            },
        })
        body = client.get("/api/v1/devices").json()
        assert body["count"] == 1
        assert body["devices"][0]["device_id"] == "node-legacy-001"

    def test_synthetic_admin_context_used_when_auth_disabled(self, client_no_auth):
        """Listing deployments should succeed even without any headers."""
        client, _ = client_no_auth
        resp = client.get("/api/v1/deployments")  # no Authorization header
        assert resp.status_code == 200
