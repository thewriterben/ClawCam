"""Analytics over ClawCam detection data — pure, storage-agnostic roll-ups.

Kept deliberately free of DB/framework imports so the analysis logic can be unit-tested
in isolation and reused anywhere (REST, MCP tools, the brain adapter).
"""

from .activity import build_activity_report
from .diversity import build_diversity_report
from .site import build_site_report
from .trends import build_trend_report

__all__ = [
    "build_activity_report",
    "build_diversity_report",
    "build_site_report",
    "build_trend_report",
]
