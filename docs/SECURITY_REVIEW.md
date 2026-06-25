# Gateway Security Review — Phase 13 hardening

Scope: `gateway/clawcam_gateway/` and `brain/oh-ben-claw-adapter/`. Findings are ranked by
severity. Each is marked **Fixed** (addressed in this pass, with regression tests in
`tests/gateway/test_security_hardening.py`) or **Recommended** (deferred; see rationale).

## Fixed

### H1 — Webhook SSRF (Fixed)
`alerts/webhook.py` previously passed any user-supplied URL straight to `urllib` with no
validation. Webhook URLs are user-controlled (per alert rule and per schedule action), so a
URL could target cloud metadata (`169.254.169.254`), `localhost`, or RFC1918 hosts, and a
public URL could 302-redirect to an internal target; non-HTTP schemes (`file://`) were also
accepted.

**Fix:** `deliver_webhook` now enforces, by default, an http/https-only scheme check, resolves
the host and rejects loopback/private/link-local/reserved/multicast/unspecified addresses, and
does not follow redirects. A new `allow_private` parameter (wired to
`CLAWCAM_WEBHOOK_ALLOW_PRIVATE_HOSTS`, default **false**, threaded through `AlertEvaluator` and
`ScheduleEngine`) re-enables internal targets for trusted LAN/dev use.

### H2 / H3 — Path traversal in uploads (Fixed)
`POST /api/v1/media/{event_id}`, `/api/v1/audio/{event_id}`, and `/api/v1/firmware` built the
on-disk filename from an unsanitized path param / client filename, allowing writes outside the
media directory (arbitrary-file-write).

**Fix:** `event_id` is validated against a strict allowlist (`_safe_path_component`), the file
extension is restricted to a per-endpoint allowlist (`_safe_suffix`), firmware filenames are
reduced to a sanitized basename, and every destination is `.resolve()`d and asserted to be
contained within its target directory (else `400`).

### M1 — Unbounded upload size (Fixed)
The upload handlers buffered the whole body with no cap. Added `MAX_MEDIA_BYTES` (50 MB) and
`MAX_FIRMWARE_BYTES` (32 MB); oversize uploads return `413`.

## Recommended (deferred)

### H4 — Auth coverage & multi-tenant scoping
Auth is disabled by default (`CLAWCAM_AUTH_ENABLED=false`) — an intentional choice for
single-user field gateways (see `docs/STATUS.md`, Phase 7). When enabled, several read/listing
endpoints are not filtered by `deployment_id`, so one tenant's key can read another tenant's
devices/events/detections. Recommended follow-up (a deliberate, test-heavy change, not bundled
here): add `Depends(require_write)`/`require_read` to the upload and data endpoints and thread
`auth.deployment_id` into the listing queries; consider defaulting auth on when bound to a
non-loopback interface.

### M2 — API-key hash
Tokens are high-entropy (`secrets.token_urlsafe(32)`) and stored as bare SHA-256, looked up by
SQL equality. Low exploitability given the entropy; to harden, fetch by key prefix then
`hmac.compare_digest`, or HMAC with a server-side pepper.

### M3 — Firmware integrity on serve
SHA-256 is computed and stored at upload but not re-verified when the binary is served. Node
must verify the published hash before flashing; recommend the gateway also recompute on serve
and reject on mismatch.

### L1 — Verbose error detail
A few handlers return `str(exc)` to the client, which can leak internal field/DB names. Return
a generic message and log details server-side.

## Verified safe
- **SQL injection** — all queries parameterized; the few f-string SQL sites interpolate only
  hardcoded, allow-listed column names, never user values.
- **Token generation** — 256-bit `secrets` tokens, plaintext returned once, only hash stored.
- **Scope model** — `admin ≥ write ≥ read` logic is correct where applied; expired/revoked keys
  handled.
- **Secrets in logs / audit** — no token logging; the adapter tool-call audit records only tool
  name + decision, not arguments.
