"""Webhook delivery for ClawCam alert notifications.

Sends a JSON POST to a configured URL when an alert rule fires.
Uses only the standard library (urllib.request) — no extra dependencies.

Design
------
- Never raises: returns (success: bool, status_code: int | None, error: str | None).
- Timeout defaults to 5 seconds — field gateways may be on slow links.
- Content-Type is always application/json; charset utf-8.
- Caller logs failures; delivery status is recorded in the alert_events table.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 5  # seconds


def deliver_webhook(
    url: str,
    payload: dict[str, Any],
    timeout: int = _DEFAULT_TIMEOUT,
) -> tuple[bool, int | None, str | None]:
    """POST *payload* as JSON to *url*.

    Returns:
        (success, http_status_code, error_message)
        success is True only when the server responds with 2xx.
    """
    if not url:
        return False, None, "no webhook URL configured"

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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
