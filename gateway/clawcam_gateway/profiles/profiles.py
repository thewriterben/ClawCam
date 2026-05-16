"""Device profile catalog with per-profile behavioral defaults.

Profiles are the product class a device belongs to. Each profile sets
sensible defaults for the firmware (sleep policy, capture cadence) and the
gateway (which detectors to run, default alert thresholds, audio capture
on/off). Operators can still override anything via apply_config_patch or
alert rules — these are just the baseline expectations of "what kind of
camera is this".

The full list is intentionally narrow at first. New profiles can be added
without a migration: they're string enum values, validated at the API
boundary, and the dispatch tables here grow with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Profile string constants ─────────────────────────────────────────────────

PROFILE_GENERAL = "general"
PROFILE_WILDLIFE = "wildlife_trail_camera"
PROFILE_HOME_SECURITY_OUTDOOR = "home_security_outdoor"
PROFILE_HOME_SECURITY_INDOOR = "home_security_indoor"
PROFILE_BIRD_FEEDER = "bird_feeder"
PROFILE_HUMMINGBIRD_FEEDER = "hummingbird_feeder"
PROFILE_LIVESTOCK = "livestock_watch"
PROFILE_APIARY = "apiary"
PROFILE_GARDEN = "garden"
PROFILE_DRIVEWAY = "driveway"

PROFILES: tuple[str, ...] = (
    PROFILE_GENERAL,
    PROFILE_WILDLIFE,
    PROFILE_HOME_SECURITY_OUTDOOR,
    PROFILE_HOME_SECURITY_INDOOR,
    PROFILE_BIRD_FEEDER,
    PROFILE_HUMMINGBIRD_FEEDER,
    PROFILE_LIVESTOCK,
    PROFILE_APIARY,
    PROFILE_GARDEN,
    PROFILE_DRIVEWAY,
)

DEFAULT_PROFILE = PROFILE_GENERAL


def is_valid_profile(value: str | None) -> bool:
    return value in PROFILES


# ── Per-profile defaults ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProfileDefaults:
    """Behavioral defaults for a device profile.

    Attributes
    ----------
    profile:               Profile string this row describes.
    description:           One-line description shown to operators / the brain.
    default_detectors:     Ordered list of detector names the inference
                           orchestrator should run on each image. Names
                           must resolve in ``inference.registry``.
    audio_enabled:         Whether the firmware should capture audio.
    default_capture_interval_s: Firmware deep-sleep duration for periodic
                                capture profiles. None = PIR-only trigger.
    capture_continuous:    True for always-on capture (security cameras),
                           False for sleep-driven trail cams.
    alert_priority_weight: Multiplier applied to alert priority. Security
                           profiles get higher weights so their alerts
                           rank above wildlife in mixed deployments.
    default_min_confidence: Default ``min_confidence`` for new alert rules
                            scoped to devices of this profile.
    notes:                 Free-form metadata, surfaced in /api/v1/profiles.
    """

    profile: str
    description: str
    default_detectors: tuple[str, ...] = ("mock_detector",)
    audio_enabled: bool = False
    default_capture_interval_s: int | None = None
    capture_continuous: bool = False
    alert_priority_weight: float = 1.0
    default_min_confidence: float = 0.5
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "description": self.description,
            "default_detectors": list(self.default_detectors),
            "audio_enabled": self.audio_enabled,
            "default_capture_interval_s": self.default_capture_interval_s,
            "capture_continuous": self.capture_continuous,
            "alert_priority_weight": self.alert_priority_weight,
            "default_min_confidence": self.default_min_confidence,
            "notes": self.notes,
        }


_PROFILE_DEFAULTS: dict[str, ProfileDefaults] = {
    PROFILE_GENERAL: ProfileDefaults(
        profile=PROFILE_GENERAL,
        description="Generic profile with no domain-specific tuning.",
    ),
    PROFILE_WILDLIFE: ProfileDefaults(
        profile=PROFILE_WILDLIFE,
        description="PIR-triggered trail camera for wildlife monitoring.",
        default_detectors=("megadetector_v5", "mock_detector"),
        default_capture_interval_s=300,  # 5-minute wake cycle as a fallback
        notes={"trigger": "pir", "field_deployable": True},
    ),
    PROFILE_HOME_SECURITY_OUTDOOR: ProfileDefaults(
        profile=PROFILE_HOME_SECURITY_OUTDOOR,
        description="Always-on outdoor security camera (porch, driveway, yard).",
        default_detectors=("megadetector_v5", "face_recognizer", "plate_ocr"),
        audio_enabled=True,
        capture_continuous=True,
        alert_priority_weight=2.0,
        default_min_confidence=0.6,
        notes={"requires_mains_power": True},
    ),
    PROFILE_HOME_SECURITY_INDOOR: ProfileDefaults(
        profile=PROFILE_HOME_SECURITY_INDOOR,
        description="Indoor security camera; respects armed/disarmed state.",
        default_detectors=("megadetector_v5", "face_recognizer", "audio_glassbreak"),
        audio_enabled=True,
        capture_continuous=True,
        alert_priority_weight=2.5,
        default_min_confidence=0.7,
        notes={"privacy_zones_strongly_recommended": True},
    ),
    PROFILE_BIRD_FEEDER: ProfileDefaults(
        profile=PROFILE_BIRD_FEEDER,
        description="Backyard bird feeder camera with audio (BirdNET).",
        default_detectors=("megadetector_v5", "bird_classifier", "audio_birdnet"),
        audio_enabled=True,
        default_capture_interval_s=60,
        notes={"peak_hours": ["dawn", "dusk"], "ebird_integration_recommended": True},
    ),
    PROFILE_HUMMINGBIRD_FEEDER: ProfileDefaults(
        profile=PROFILE_HUMMINGBIRD_FEEDER,
        description="High-FPS short-burst camera at a hummingbird feeder.",
        default_detectors=("bird_classifier",),
        default_capture_interval_s=30,
        notes={"high_fps_burst": True, "burst_seconds": 3},
    ),
    PROFILE_LIVESTOCK: ProfileDefaults(
        profile=PROFILE_LIVESTOCK,
        description="Pasture / barn monitoring for predators and herd events.",
        default_detectors=("megadetector_v5",),
        default_capture_interval_s=120,
        alert_priority_weight=1.5,
        notes={"alert_on_predators": ["coyote", "mountain_lion", "wolf"]},
    ),
    PROFILE_APIARY: ProfileDefaults(
        profile=PROFILE_APIARY,
        description="Beehive activity, wasp intrusion, and swarm detection.",
        default_detectors=("mock_detector",),  # placeholder — needs apiary model
        audio_enabled=True,
        default_capture_interval_s=300,
        notes={"close_up": True, "warns_swarms": True},
    ),
    PROFILE_GARDEN: ProfileDefaults(
        profile=PROFILE_GARDEN,
        description="Garden pest detection and plant growth monitoring.",
        default_detectors=("megadetector_v5",),
        default_capture_interval_s=900,  # 15 min — slow growth
        notes={"pest_alerts": True, "growth_stage_tracking": True},
    ),
    PROFILE_DRIVEWAY: ProfileDefaults(
        profile=PROFILE_DRIVEWAY,
        description="Driveway vehicle / package / visitor counter.",
        default_detectors=("megadetector_v5", "plate_ocr"),
        capture_continuous=True,
        alert_priority_weight=1.5,
        default_min_confidence=0.55,
        notes={"plate_ocr_enabled": True},
    ),
}


def get_profile_defaults(profile: str) -> ProfileDefaults:
    """Return the defaults for *profile*, or the general profile if unknown."""
    return _PROFILE_DEFAULTS.get(profile, _PROFILE_DEFAULTS[DEFAULT_PROFILE])
