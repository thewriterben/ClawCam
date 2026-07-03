"""Analytics over ClawCam detection data — pure, storage-agnostic roll-ups.

Kept deliberately free of DB/framework imports so the analysis logic can be unit-tested
in isolation and reused anywhere (REST, MCP tools, the brain adapter).
"""

from .activity import build_activity_report

__all__ = ["build_activity_report"]
