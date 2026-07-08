"""Analytics over ClawCam detection data — pure, storage-agnostic roll-ups.

Kept deliberately free of DB/framework imports so the analysis logic can be unit-tested
in isolation and reused anywhere (REST, MCP tools, the brain adapter).
"""

from .abundance import build_abundance_report
from .activity import build_activity_report
from .anomaly import build_anomaly_report
from .calibration import build_calibration_report
from .compare import build_comparison_report
from .cooccurrence import build_cooccurrence_report
from .daily import build_daily_site_section
from .diversity import build_diversity_report
from .encounters import build_encounter_report
from .environment import build_environment_report
from .site import build_site_report
from .species import build_species_profile
from .trends import build_trend_report
from .weather_activity import build_weather_activity_report

__all__ = [
    "build_abundance_report",
    "build_activity_report",
    "build_anomaly_report",
    "build_calibration_report",
    "build_comparison_report",
    "build_cooccurrence_report",
    "build_daily_site_section",
    "build_diversity_report",
    "build_encounter_report",
    "build_environment_report",
    "build_site_report",
    "build_species_profile",
    "build_trend_report",
    "build_weather_activity_report",
]
