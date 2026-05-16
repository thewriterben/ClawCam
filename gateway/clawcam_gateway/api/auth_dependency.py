"""FastAPI auth dependencies for ClawCam gateway endpoints.

Resolves the calling deployment + scope from inbound request headers:
  - ``Authorization: Bearer <token>``
  - ``X-Api-Key: <token>`` (fallback for clients that can't set Authorization)

When ``CLAWCAM_AUTH_ENABLED=false`` (the default), all requests get a
synthetic admin context against the ``default`` deployment so existing
deployments and tests keep working without code changes.

Usage in route handlers::

    from fastapi import Depends
    from clawcam_gateway.api.auth_dependency import (
        get_auth_context, require_write, require_admin
    )

    @app.get("/api/v1/things")
    def list_things(auth = Depends(get_auth_context)):
        return db.list_things(deployment_id=auth.deployment_id)

    @app.post("/api/v1/things")
    def create_thing(auth = Depends(require_write)):
        ...

``create_app`` is responsible for storing the auth_enabled flag and the
database instance on ``app.state`` so these dependencies can find them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request

from clawcam_gateway.auth import (
    AuthContext,
    SCOPE_ADMIN,
    SCOPE_READ,
    SCOPE_WRITE,
    ScopeRequired,
    hash_api_key,
)
from clawcam_gateway.auth.tokens import synthetic_admin_context


def _extract_token(request: Request) -> str | None:
    """Pull a bearer token from the request, or return None."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None
    key_header = request.headers.get("x-api-key", "")
    if key_header:
        return key_header.strip()
    return None


def get_auth_context(request: Request) -> AuthContext:
    """Resolve the calling deployment + scope from request headers.

    Reads ``request.app.state.auth_enabled`` (bool) and
    ``request.app.state.db`` (``GatewayDatabase``) — both set by
    ``create_app``.
    """
    state = request.app.state
    auth_enabled = bool(getattr(state, "auth_enabled", False))
    if not auth_enabled:
        ctx = synthetic_admin_context()
        request.state.auth = ctx
        return ctx

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing API key")

    db = state.db
    record = db.get_api_key_by_hash(hash_api_key(token))
    if record is None:
        raise HTTPException(status_code=401, detail="invalid API key")
    if not record["enabled"]:
        raise HTTPException(status_code=403, detail="API key is revoked")
    if record.get("expires_at"):
        now_iso = datetime.now(timezone.utc).isoformat()
        if record["expires_at"] < now_iso:
            raise HTTPException(status_code=403, detail="API key has expired")

    # Best-effort last_used_at update — never blocks the request.
    db.touch_api_key(record["key_id"])

    ctx = AuthContext(
        deployment_id=record["deployment_id"],
        scope=record["scope"],
        key_id=record["key_id"],
        key_name=record["name"],
        authenticated=True,
    )
    request.state.auth = ctx
    return ctx


def _make_scope_guard(required_scope: str):
    """Build a FastAPI dependency that enforces a given minimum scope."""

    def _guard(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        try:
            auth.require(required_scope)
        except ScopeRequired as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return auth

    _guard.__name__ = f"require_{required_scope}"
    return _guard


require_read = _make_scope_guard(SCOPE_READ)
require_write = _make_scope_guard(SCOPE_WRITE)
require_admin = _make_scope_guard(SCOPE_ADMIN)
