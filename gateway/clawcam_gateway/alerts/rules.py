"""Alert rule data model and match logic for ClawCam gateway.

An AlertRule describes the conditions under which a notification should fire:
  - which device (optional; None = all devices)
  - which detection label ("animal", "person", "vehicle"; None = any)
  - minimum confidence threshold
  - species substring match (case-insensitive; None = any)

Rules are stored in SQLite and evaluated after each inference result is saved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AlertRule:
    """A persistent notification rule that fires on matching inference results.

    Attributes
    ----------
    rule_id:          UUID string assigned at creation.
    name:             Human-readable label for the rule.
    label:            Detection category to match: "animal", "person", "vehicle",
                      or None to match any label.
    min_confidence:   Minimum top_confidence required to fire (0.0–1.0).
    species_pattern:  Case-insensitive substring to match against top_species.
                      None = match any species (or no species).
    device_id:        If set, only fire for events from this device.
    webhook_url:      HTTP(S) endpoint to POST the alert payload.
                      If empty/None, the rule is stored but no delivery occurs.
    enabled:          Whether the rule is active.
    created_at:       ISO 8601 UTC creation timestamp.
    """

    rule_id: str
    name: str
    label: str | None = None
    min_confidence: float = 0.5
    species_pattern: str | None = None
    device_id: str | None = None
    webhook_url: str | None = None
    enabled: bool = True
    created_at: str = ""
    # Phase 8: rule fires only when the device or its deployment is in this state.
    # None = state-agnostic (fires regardless of state).
    required_state: str | None = None

    # ── Matching ──────────────────────────────────────────────────────────

    def matches(
        self,
        inference_result: dict[str, Any],
        device_id: str | None = None,
        current_state: str | None = None,
    ) -> bool:
        """Return True if this rule fires for the given inference result dict.

        Args:
            inference_result: Dict from GatewayDatabase.get_inference_result or
                              list_inference_results — keys: top_label,
                              top_confidence, top_species, event_id.
            device_id:        The device_id that uploaded the media (device filter).
            current_state:    Current effective state of the device (or its
                              deployment). When the rule's ``required_state``
                              is set, the two must match for the rule to fire.
        """
        if not self.enabled:
            return False

        # Device filter
        if self.device_id and device_id and self.device_id != device_id:
            return False

        # State gate (Phase 8). If a state is required but unknown, do not fire.
        if self.required_state is not None and current_state != self.required_state:
            return False

        # Confidence gate
        conf = inference_result.get("top_confidence") or 0.0
        if conf < self.min_confidence:
            return False

        # Label filter
        if self.label is not None:
            if inference_result.get("top_label") != self.label:
                return False

        # Species pattern
        if self.species_pattern is not None:
            species = (inference_result.get("top_species") or "").lower()
            if self.species_pattern.lower() not in species:
                return False

        return True

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "label": self.label,
            "min_confidence": self.min_confidence,
            "species_pattern": self.species_pattern,
            "device_id": self.device_id,
            "webhook_url": self.webhook_url,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "required_state": self.required_state,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AlertRule":
        return cls(
            rule_id=d["rule_id"],
            name=d["name"],
            label=d.get("label"),
            min_confidence=float(d.get("min_confidence", 0.5)),
            species_pattern=d.get("species_pattern"),
            device_id=d.get("device_id"),
            webhook_url=d.get("webhook_url"),
            enabled=bool(d.get("enabled", True)),
            created_at=d.get("created_at", ""),
            required_state=d.get("required_state"),
        )
