"""Per-profile alert-rule templates.

Turns a device profile's intent (its default confidence + metadata notes like
``alert_on_predators``) into a set of ready-to-create ``AlertRule`` dicts, so a
newly provisioned camera is useful out of the box instead of starting with zero
rules.

Templates are partial: they carry ``name``, ``label``, ``min_confidence``,
``species_pattern``, ``required_state``, and ``enabled`` — the caller assigns
``rule_id``, ``created_at``, ``device_id``, and ``webhook_url`` when persisting.

Note: the alert evaluator runs on *visual* inference results (labels
``animal``/``person``/``vehicle`` + species). Acoustic events (glass_break, etc.)
are scored in the audio pipeline and aren't yet routed through alert rules, so
these templates intentionally cover the visual labels only.
"""

from __future__ import annotations

from typing import Any

from clawcam_gateway.profiles import (
    PROFILE_DRIVEWAY,
    PROFILE_GARDEN,
    PROFILE_HOME_SECURITY_INDOOR,
    PROFILE_HOME_SECURITY_OUTDOOR,
    PROFILE_LIVESTOCK,
    PROFILE_WILDLIFE,
    get_profile_defaults,
)


def _template(
    name: str,
    label: str | None = None,
    min_confidence: float = 0.5,
    species_pattern: str | None = None,
    required_state: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "min_confidence": round(float(min_confidence), 3),
        "species_pattern": species_pattern,
        "required_state": required_state,
        "enabled": True,
    }


def alert_rule_templates_for_profile(profile: str) -> list[dict[str, Any]]:
    """Return recommended alert-rule templates for *profile* (possibly empty).

    Derives thresholds from the profile's ``default_min_confidence`` and reads
    profile metadata (e.g. ``notes["alert_on_predators"]``) so the templates stay
    in sync with the profile catalog.
    """
    defaults = get_profile_defaults(profile)
    mc = defaults.default_min_confidence
    notes = defaults.notes
    out: list[dict[str, Any]] = []

    if profile == PROFILE_HOME_SECURITY_OUTDOOR:
        out.append(_template("Person detected", label="person", min_confidence=mc))
        out.append(_template("Vehicle detected", label="vehicle", min_confidence=mc))
    elif profile == PROFILE_HOME_SECURITY_INDOOR:
        # Only fire while the device/deployment is armed.
        out.append(_template("Person detected (armed)", label="person",
                             min_confidence=mc, required_state="armed"))
    elif profile == PROFILE_WILDLIFE:
        # Human presence on a wildlife cam is worth flagging (e.g. intrusion).
        out.append(_template("Human presence", label="person",
                             min_confidence=max(mc, 0.6)))
    elif profile == PROFILE_LIVESTOCK:
        for predator in notes.get("alert_on_predators", []):
            nice = str(predator).replace("_", " ")
            out.append(_template(f"Predator near herd: {nice}", label="animal",
                                 species_pattern=nice, min_confidence=mc))
    elif profile == PROFILE_DRIVEWAY:
        out.append(_template("Vehicle in driveway", label="vehicle", min_confidence=mc))
        out.append(_template("Visitor (person) at driveway", label="person", min_confidence=mc))
    elif profile == PROFILE_GARDEN:
        out.append(_template("Animal in garden (possible pest)", label="animal",
                             min_confidence=mc))

    # general, bird_feeder, hummingbird_feeder, apiary -> no opinionated security
    # rules (passive observation or no suitable model yet).
    return out
