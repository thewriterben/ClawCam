"""API token generation, hashing, and scope helpers for ClawCam gateway."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any


# ── Scope model ───────────────────────────────────────────────────────────────
#
# Scopes are ordered. A key issued with a higher scope satisfies any lower
# scope's requirement. ``admin`` ≥ ``write`` ≥ ``read``.

SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_ADMIN = "admin"

SCOPES = (SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN)

_SCOPE_LEVEL: dict[str, int] = {SCOPE_READ: 0, SCOPE_WRITE: 1, SCOPE_ADMIN: 2}


def scope_satisfies(actual: str, required: str) -> bool:
    """Return True if a token with *actual* scope can access something needing *required*."""
    return _SCOPE_LEVEL.get(actual, -1) >= _SCOPE_LEVEL.get(required, 99)


# ── Auth context dataclass ────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuthContext:
    """The result of resolving an inbound request against the api_keys table.

    Injected into endpoint handlers via the FastAPI dependency in
    ``api/auth_dependency.py``. Downstream code uses ``deployment_id`` to
    scope SQL queries and ``scope`` to gate mutating actions.
    """

    deployment_id: str
    scope: str
    key_id: str | None = None     # None when auth is disabled (synthetic context)
    key_name: str | None = None
    authenticated: bool = True

    def require(self, scope: str) -> None:
        """Raise ``ScopeRequired`` if this context does not satisfy *scope*."""
        if not scope_satisfies(self.scope, scope):
            raise ScopeRequired(needed=scope, actual=self.scope)


class ScopeRequired(Exception):
    """Raised when a request's auth scope is insufficient for the requested action."""

    def __init__(self, needed: str, actual: str):
        self.needed = needed
        self.actual = actual
        super().__init__(f"requires scope '{needed}', got '{actual}'")


# ── Token generation + hashing ────────────────────────────────────────────────


def generate_api_key(prefix: str = "cc") -> str:
    """Return a fresh API key string.

    Format: ``{prefix}_{43 url-safe base64 chars}``.

    The prefix is purely cosmetic — it lets users tell the key type at a
    glance and lets log scrubbers redact obvious key shapes. The 32 bytes
    of entropy is well above the 128-bit security margin recommended for
    long-lived API tokens.
    """
    body = secrets.token_urlsafe(32)
    return f"{prefix}_{body}"


def hash_api_key(token: str) -> str:
    """Return the lowercase hex SHA-256 of *token*.

    The DB stores only the hash. Tokens are returned to the user once at
    creation time and never recoverable afterwards.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def redact_key(token: str) -> str:
    """Return a shortened, log-safe form of a key (last 4 chars only)."""
    return f"…{token[-4:]}" if len(token) >= 4 else "…"


# ── Common helpers ────────────────────────────────────────────────────────────


def synthetic_admin_context(deployment_id: str = "default") -> AuthContext:
    """Return a fully privileged context for when auth is disabled."""
    return AuthContext(
        deployment_id=deployment_id,
        scope=SCOPE_ADMIN,
        key_id=None,
        key_name="auth-disabled",
        authenticated=False,
    )


def auth_response_payload(key_id: str, plaintext_key: str, name: str, scope: str,
                          deployment_id: str, created_at: str,
                          expires_at: str | None = None) -> dict[str, Any]:
    """Standard response shape for newly issued keys.

    The plaintext key is included only on creation responses; it is never
    returned by list endpoints because it isn't stored.
    """
    return {
        "ok": True,
        "key_id": key_id,
        "name": name,
        "scope": scope,
        "deployment_id": deployment_id,
        "token": plaintext_key,
        "created_at": created_at,
        "expires_at": expires_at,
        "warning": "The 'token' value is shown ONCE. Store it now; it cannot be retrieved later.",
    }
