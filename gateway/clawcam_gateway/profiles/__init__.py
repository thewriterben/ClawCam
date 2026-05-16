"""Device profiles and runtime state machine for ClawCam gateway.

A *profile* is the product class a device belongs to — wildlife trail camera,
home security indoor/outdoor, bird feeder, hummingbird feeder, livestock,
apiary, garden, driveway, or generic. Profile choice drives default behavior:
which detectors run, how often the firmware wakes up, how aggressively to
alert, whether audio is captured, etc.

A *state* is the runtime mode the device is in right now — ``normal``,
``armed``, ``disarmed``, ``away``, ``vacation``, ``feeding``,
``maintenance``. States are deliberately free-form (any-to-any transitions)
because real deployments do unexpected things; we audit every transition
in the ``state_transitions`` table instead of trying to enforce a finite
state machine that always becomes wrong.

Both profile and state live at the device level. Deployments carry a
default state that devices inherit when their own state is unset. This
mirrors how an alarm panel sets the whole house to ``armed`` while the
individual cameras still expose their per-device state for diagnostics.
"""

from clawcam_gateway.profiles.profiles import (
    DEFAULT_PROFILE,
    PROFILE_BIRD_FEEDER,
    PROFILE_DRIVEWAY,
    PROFILE_GARDEN,
    PROFILE_GENERAL,
    PROFILE_HOME_SECURITY_INDOOR,
    PROFILE_HOME_SECURITY_OUTDOOR,
    PROFILE_HUMMINGBIRD_FEEDER,
    PROFILE_LIVESTOCK,
    PROFILE_APIARY,
    PROFILE_WILDLIFE,
    PROFILES,
    ProfileDefaults,
    get_profile_defaults,
    is_valid_profile,
)
from clawcam_gateway.profiles.states import (
    DEFAULT_STATE,
    STATE_ARMED,
    STATE_AWAY,
    STATE_DISARMED,
    STATE_FEEDING,
    STATE_MAINTENANCE,
    STATE_NORMAL,
    STATE_VACATION,
    STATES,
    is_valid_state,
)

__all__ = [
    # Profile constants
    "DEFAULT_PROFILE",
    "PROFILE_APIARY",
    "PROFILE_BIRD_FEEDER",
    "PROFILE_DRIVEWAY",
    "PROFILE_GARDEN",
    "PROFILE_GENERAL",
    "PROFILE_HOME_SECURITY_INDOOR",
    "PROFILE_HOME_SECURITY_OUTDOOR",
    "PROFILE_HUMMINGBIRD_FEEDER",
    "PROFILE_LIVESTOCK",
    "PROFILE_WILDLIFE",
    "PROFILES",
    "ProfileDefaults",
    "get_profile_defaults",
    "is_valid_profile",
    # State constants
    "DEFAULT_STATE",
    "STATE_ARMED",
    "STATE_AWAY",
    "STATE_DISARMED",
    "STATE_FEEDING",
    "STATE_MAINTENANCE",
    "STATE_NORMAL",
    "STATE_VACATION",
    "STATES",
    "is_valid_state",
]
