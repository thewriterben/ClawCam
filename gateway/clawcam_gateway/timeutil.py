"""Timestamp parsing shared across the gateway.

The database mixes two wall-clock formats: SQLite's ``datetime('now')``
(``YYYY-MM-DD HH:MM:SS``) and Python's ``datetime.isoformat()``
(``YYYY-MM-DDTHH:MM:SS+00:00``). Comparing them as raw strings is wrong
(``' ' < 'T'`` shifts every SQLite-stamped row a full day at window
boundaries), so any code comparing timestamps must go through
``parse_ts`` and compare aware datetimes.
"""

from __future__ import annotations

from datetime import datetime, timezone


def parse_ts(value: object) -> datetime | None:
    """Parse a timestamp into an aware UTC datetime, or None if unparseable.

    Accepts ISO 8601 with ``T`` or space separators, optional fractional
    seconds, ``Z`` or numeric offsets, and bare dates (midnight UTC).
    Naive values are assumed to be UTC (both producers stamp UTC).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
