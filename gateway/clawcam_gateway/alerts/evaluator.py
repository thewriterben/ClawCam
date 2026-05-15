"""AlertEvaluator: run after inference, check rules, fire webhooks.

Called as a FastAPI BackgroundTask after each inference result is saved.
Never raises — delivery failures are recorded in the alert_events table but
never propagate to the caller.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from clawcam_gateway.alerts.rules import AlertRule
from clawcam_gateway.alerts.webhook import deliver_webhook

if TYPE_CHECKING:
    from clawcam_gateway.storage.database import GatewayDatabase

logger = logging.getLogger(__name__)


class AlertEvaluator:
    """Evaluates enabled alert rules against a fresh inference result.

    Args:
        db:              GatewayDatabase instance for rule and event persistence.
        default_webhook: Global fallback webhook URL (from ``CLAWCAM_ALERT_WEBHOOK_URL``).
                         Used when a rule has no individual webhook_url.
    """

    def __init__(self, db: "GatewayDatabase", default_webhook: str | None = None):
        self._db = db
        self._default_webhook = default_webhook or ""

    def evaluate(self, event_id: str, device_id: str | None = None) -> int:
        """Check all enabled rules against the inference result for *event_id*.

        Fires webhooks for every matching rule and persists alert_events rows.

        Args:
            event_id:  The event whose inference result should be evaluated.
            device_id: The originating device (used for device-filter rules).

        Returns:
            Number of rules that matched (and fired).
        """
        try:
            result = self._db.get_inference_result(event_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEvaluator: could not fetch result for %s: %s", event_id, exc)
            return 0

        if result is None:
            return 0

        try:
            rules = self._db.list_alert_rules(enabled_only=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEvaluator: could not load rules: %s", exc)
            return 0

        fired = 0
        for rule_dict in rules:
            rule = AlertRule.from_dict(rule_dict)
            if not rule.matches(result, device_id=device_id):
                continue
            fired += 1
            self._fire(rule, result, event_id, device_id)

        return fired

    # ── Internal ──────────────────────────────────────────────────────────

    def _fire(
        self,
        rule: AlertRule,
        result: dict[str, Any],
        event_id: str,
        device_id: str | None,
    ) -> None:
        """Deliver webhook and persist alert_event row (never raises)."""
        alert_event_id = f"alert-{uuid.uuid4().hex[:12]}"
        fired_at = datetime.now(timezone.utc).isoformat()

        url = rule.webhook_url or self._default_webhook
        payload = _build_payload(alert_event_id, rule, result, event_id, device_id, fired_at)

        success, status_code, error = deliver_webhook(url, payload) if url else (False, None, "no url")

        delivery_status = "delivered" if success else "failed"
        webhook_response = str(status_code) if status_code is not None else (error or "no url")

        try:
            self._db.add_alert_event({
                "alert_event_id": alert_event_id,
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "event_id": event_id,
                "device_id": device_id or "",
                "top_label": result.get("top_label") or "",
                "top_confidence": result.get("top_confidence"),
                "top_species": result.get("top_species") or "",
                "webhook_url": url,
                "delivery_status": delivery_status,
                "webhook_response": webhook_response,
                "fired_at": fired_at,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEvaluator: could not persist alert event: %s", exc)

        if success:
            logger.info(
                "Alert '%s' fired for event %s → %s (HTTP %s)",
                rule.name, event_id, url, status_code,
            )
        else:
            logger.warning(
                "Alert '%s' fired for event %s but webhook failed: %s",
                rule.name, event_id, error,
            )


def _build_payload(
    alert_event_id: str,
    rule: AlertRule,
    result: dict[str, Any],
    event_id: str,
    device_id: str | None,
    fired_at: str,
) -> dict[str, Any]:
    return {
        "alert_event_id": alert_event_id,
        "rule_id": rule.rule_id,
        "rule_name": rule.name,
        "event_id": event_id,
        "device_id": device_id,
        "fired_at": fired_at,
        "detection": {
            "top_label": result.get("top_label"),
            "top_confidence": result.get("top_confidence"),
            "top_species": result.get("top_species"),
            "model_name": result.get("model_name"),
            "ran_at": result.get("ran_at"),
        },
    }
