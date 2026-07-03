"""AlertEvaluator: run after inference, check rules, fire webhooks.

Called as a FastAPI BackgroundTask after each inference result is saved.
Never raises — delivery failures are recorded in the alert_events table but
never propagate to the caller.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from clawcam_gateway.alerts.rules import AlertRule, severity_rank
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

    def __init__(self, db: "GatewayDatabase", default_webhook: str | None = None,
                 allow_private_hosts: bool = False, dedup_window_s: int = 0,
                 min_severity: str = "info"):
        self._db = db
        self._default_webhook = default_webhook or ""
        self._allow_private_hosts = allow_private_hosts
        # Alert polish: collapse repeat alerts within this window (0 = off), and only
        # deliver webhooks for rules at or above this severity (the alert is always
        # recorded regardless).
        self._dedup_window_s = int(dedup_window_s or 0)
        self._min_severity = min_severity or "info"

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

        # Phase 10: filter detections by detection-zone actions.
        try:
            if device_id is not None:
                zones = self._db.list_detection_zones(
                    device_id=device_id, enabled_only=True,
                )
                if zones:
                    from clawcam_gateway.zones import apply_zones_to_result
                    result, alerts_blocked = apply_zones_to_result(result, zones)
                    if alerts_blocked:
                        # Every surviving detection is in a record-only zone.
                        return 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEvaluator: zone filtering failed: %s", exc)

        # Resolve effective state: device override > deployment default > 'normal'
        current_state = self._resolve_state(device_id)

        fired = 0
        for rule_dict in rules:
            rule = AlertRule.from_dict(rule_dict)
            if not rule.matches(result, device_id=device_id, current_state=current_state):
                continue
            fired += 1
            self._fire(rule, result, event_id, device_id)

        return fired

    def evaluate_audio(self, event_id: str, device_id: str | None = None,
                       audio_id: int | None = None) -> int:
        """Check enabled rules against the audio classifications for an event.

        Mirrors :meth:`evaluate` for the acoustic pipeline: each stored audio
        classification (glass_break, alarm, scream, ...) is shaped like an
        inference result and matched against the rules. Fires + persists alert
        events for matches. Never raises.
        """
        try:
            classifications = self._db.list_audio_classifications(
                audio_id=audio_id, event_id=event_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEvaluator: could not fetch audio for %s: %s", event_id, exc)
            return 0
        if not classifications:
            return 0
        try:
            rules = self._db.list_alert_rules(enabled_only=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEvaluator: could not load rules: %s", exc)
            return 0

        current_state = self._resolve_state(device_id)
        fired = 0
        for c in classifications:
            pseudo = {
                "top_label": c.get("label"),
                "top_confidence": c.get("confidence") or 0.0,
                "top_species": c.get("species"),
                "event_id": event_id,
            }
            for rule_dict in rules:
                rule = AlertRule.from_dict(rule_dict)
                if rule.matches(pseudo, device_id=device_id, current_state=current_state):
                    fired += 1
                    self._fire(rule, pseudo, event_id, device_id)
        return fired

    def _resolve_state(self, device_id: str | None) -> str | None:
        """Return the effective state for a device, or None on lookup error."""
        if device_id is None:
            return None
        try:
            row = self._db.get_device_profile_state(device_id)
            if row is None:
                return None
            if row.get("state"):
                return row["state"]
            # Fall back to deployment-level state
            return self._db.get_deployment_state(row.get("deployment_id") or "default")
        except Exception:  # noqa: BLE001
            return None

    # ── Internal ──────────────────────────────────────────────────────────

    def _fire(
        self,
        rule: AlertRule,
        result: dict[str, Any],
        event_id: str,
        device_id: str | None,
    ) -> None:
        """Deliver webhook and persist alert_event row (never raises).

        De-dup: a repeat of the same (rule, device, label, species) within
        ``dedup_window_s`` is collapsed onto the last delivered alert (its
        ``suppressed_count`` is bumped) — no new row, no webhook. Severity gate: below
        ``min_severity`` the alert is still recorded but the webhook is skipped.
        """
        now = datetime.now(timezone.utc)
        fired_at = now.isoformat()
        top_label = result.get("top_label")
        top_species = result.get("top_species")

        # ── De-duplication ────────────────────────────────────────────────
        if self._dedup_window_s > 0:
            since = (now - timedelta(seconds=self._dedup_window_s)).isoformat()
            try:
                recent = self._db.find_recent_alert_event(
                    rule.rule_id, device_id, top_label, top_species, since,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("AlertEvaluator: dedup lookup failed: %s", exc)
                recent = None
            if recent is not None:
                try:
                    self._db.increment_alert_event_suppressed(recent["alert_event_id"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("AlertEvaluator: could not bump suppressed count: %s", exc)
                logger.info(
                    "Alert '%s' suppressed (dedup within %ss) for event %s",
                    rule.name, self._dedup_window_s, event_id,
                )
                return

        alert_event_id = f"alert-{uuid.uuid4().hex[:12]}"
        severity = rule.severity or "warning"
        url = rule.webhook_url or self._default_webhook
        payload = _build_payload(alert_event_id, rule, result, event_id, device_id, fired_at)
        payload["severity"] = severity

        # ── Minimum-severity delivery gate ────────────────────────────────
        if severity_rank(severity) < severity_rank(self._min_severity):
            success, status_code, error = False, None, "below min severity"
            delivery_status = "skipped_severity"
        elif url:
            success, status_code, error = deliver_webhook(
                url, payload, allow_private=self._allow_private_hosts,
            )
            delivery_status = "delivered" if success else "failed"
        else:
            success, status_code, error = False, None, "no url"
            delivery_status = "failed"

        webhook_response = str(status_code) if status_code is not None else (error or "no url")

        try:
            self._db.add_alert_event({
                "alert_event_id": alert_event_id,
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "event_id": event_id,
                "device_id": device_id or "",
                "top_label": top_label or "",
                "top_confidence": result.get("top_confidence"),
                "top_species": top_species or "",
                "webhook_url": url,
                "delivery_status": delivery_status,
                "webhook_response": webhook_response,
                "fired_at": fired_at,
                "severity": severity,
                "suppressed_count": 0,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEvaluator: could not persist alert event: %s", exc)

        if delivery_status == "delivered":
            logger.info(
                "Alert '%s' (%s) fired for event %s → %s (HTTP %s)",
                rule.name, severity, event_id, url, status_code,
            )
        elif delivery_status == "skipped_severity":
            logger.info(
                "Alert '%s' (%s) recorded but webhook skipped (below min severity %s)",
                rule.name, severity, self._min_severity,
            )
        else:
            logger.warning(
                "Alert '%s' (%s) fired for event %s but webhook failed: %s",
                rule.name, severity, event_id, error,
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
