"""Alert rules and webhook notification package for ClawCam gateway.

Evaluates alert rules against inference results after each media upload.
Fires webhook POSTs when a rule matches. Never blocks the ingest path.
"""

from clawcam_gateway.alerts.rules import AlertRule
from clawcam_gateway.alerts.evaluator import AlertEvaluator
from clawcam_gateway.alerts.webhook import deliver_webhook

__all__ = ["AlertRule", "AlertEvaluator", "deliver_webhook"]
