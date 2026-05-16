"""API authentication and tenancy package for ClawCam gateway.

Provides:
  - API key creation, hashing, and validation against the SQLite store
  - FastAPI dependencies that resolve the calling deployment + scope from
    `Authorization: Bearer <token>` or `X-Api-Key: <token>` headers
  - A dataclass `AuthContext` injected into request handlers so downstream
    code can filter SQL by deployment_id and enforce scope-based authorisation

Backwards compatibility:
  - When ``CLAWCAM_AUTH_ENABLED=false`` (the default), all requests are
    authenticated against a synthetic ``default`` deployment with the
    ``admin`` scope. Existing deployments and tests keep working without
    code changes.
  - When auth is enabled, requests without a valid bearer token receive 401.
"""

from clawcam_gateway.auth.tokens import (
    AuthContext,
    ScopeRequired,
    SCOPE_ADMIN,
    SCOPE_READ,
    SCOPE_WRITE,
    SCOPES,
    auth_response_payload,
    generate_api_key,
    hash_api_key,
    redact_key,
    scope_satisfies,
    synthetic_admin_context,
)

__all__ = [
    "AuthContext",
    "ScopeRequired",
    "SCOPE_ADMIN",
    "SCOPE_READ",
    "SCOPE_WRITE",
    "SCOPES",
    "auth_response_payload",
    "generate_api_key",
    "hash_api_key",
    "redact_key",
    "scope_satisfies",
    "synthetic_admin_context",
]
