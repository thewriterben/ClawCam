"""Analytics over ClawCam detection data — pure, storage-agnostic roll-ups.

Kept deliberately free of DB/framework imports so the analysis logic can be unit-tested
in isolation and reused anywhere (REST, MCP tools, the brain adapter).
"""

from .activity import build_activity_report
from .calibration import build_calibration_report
from .compare import build_comparison_report
from .daily import build_daily_site_section
from .diversity import build_diversity_report
from .encounters import build_encounter_report
from .site import build_site_report
from .trends import build_trend_report

__all__ = [
    "build_activity_report",
    "build_calibration_report",
    "build_comparison_report",
    "build_daily_site_section",
    "build_diversity_report",
    "build_encounter_report",
    "build_site_report",
    "build_trend_report",
]
