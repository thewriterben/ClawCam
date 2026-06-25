"""Webhook delivery for ClawCam alert notifications.

Sends a JSON POST to a configured URL when an alert rule fires.
Uses only the standard library (urllib.request) — no extra dependencies.

Design
------
- Never raises: returns (success: bool, status_code: int | None, error: str | None).
- Timeout defaults to 5 seconds — field gateways may be on slow links.
- Content-Type is always application/json; charset utf-8.
- Caller logs failures; delivery status is recorded in the alert_events table.

Security (SSRF)
---------------
Webhook URLs are user-supplied (per alert rule / schedule action), so by default
delivery is restricted to public http(s) endpoints:
- only the ``http`` and ``https`` schemes are allowed;
- the hostname is resolved and rejected if ANY resolved address is loopback,
  private (RFC1918), link-local (incl. cloud metadata 169.254.0.0/16),
  reserved, multicast, or unspecified;
- HTTP redirects are not followed (a redirect could otherwise bounce to an
  internal target after passing the initial check).
Set ``allow_private=True`` (wired to ``CLAWCAM_WEBHOOK_ALLOW_PRIVATE_HOSTS``) to
permit internal targets — intended for trusted LAN deployments and tests.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 5  # seconds
_ALLOWED_SCHEMES = ("http", "https")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so a public URL cannot bounce to an internal target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise urllib.error.HTTPError(req.full_url, code, f"redirect blocked → {newurl}", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect())


def _validate_public_url(url: str) -> str | None:
    """Return an error string if *url* is not a safe public http(s) target, else None."""
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        return f"blocked: unsupported scheme {parts.scheme!r}"
    host = parts.hostname
    if not host:
        return "blocked: missing host"
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError as exc:
        return f"blocked: cannot resolve host ({exc})"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return f"blocked: non-public address {ip}"
    return None


def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    timeout: int = _DEFAULT_TIMEOUT,
    allow_private: bool = False,
) -> tuple[bool, int | None, str | None]:
    """POST *payload* as JSON to *url*.

    Returns:
        (success, http_status_code, error_message)
        success is True only when the server responds with 2xx.

    When *allow_private* is False (the default), the target is restricted to
    public http(s) addresses (SSRF guard); see module docstring.
    """
    if not url:
        return False, None, "no webhook URL configured"

    if not allow_private:
        err = _validate_public_url(url)
        if err is not None:
            logger.warning("webhook blocked %s → %s", url, err)
            return False, None, err

    body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ClawCam-Gateway/0.1",
        },
        method="POST",
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            status = resp.status
            if 200 <= status < 300:
                return True, status, None
            return False, status, f"server returned {status}"
    except urllib.error.HTTPError as exc:
        logger.warning("webhook HTTP error %s → %s", url, exc)
        return False, exc.code, str(exc)
    except urllib.error.URLError as exc:
        logger.warning("webhook URL error %s → %s", url, exc.reason)
        return False, None, str(exc.reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("webhook unexpected error %s → %s", url, exc)
        return False, None, str(exc)
