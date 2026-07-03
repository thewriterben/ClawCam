"""Alert digest — roll up recent alert events into a compact summary.

The per-event alerts (webhooks, dashboard) answer "what just happened?". A digest
answers "what happened over the last day?" — grouped by rule and by species, with the
suppressed (de-duplicated) count folded in. Delivered on a schedule via the scheduler's
``alert_digest`` action, or pulled from ``GET /api/v1/alerts/digest``.

Mirrors Oh-Ben-Claw's periodic escalation digest. Pure and testable — no I/O.
"""

from __future__ import annotations

from typing import Any


def _ranked(counts: dict[str, int]) -> list[dict[str, Any]]:
    """Counts as a list, most frequent first (ties broken alphabetically)."""
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def build_alert_digest(events: list[dict[str, Any]], window_label: str = "") -> dict[str, Any]:
    """Summarise a list of ``alert_events`` rows.

    Args:
        events:       Rows from ``GatewayDatabase.list_alert_events`` (each a dict with
                      ``rule_name``, ``top_species``/``top_label``, ``delivery_status``,
                      ``suppressed_count``).
        window_label: Human span the digest covers, e.g. ``"24h"`` or ``"86400s"``.

    Returns a compact, JSON-serialisable summary: totals, delivery breakdown, and the
    counts grouped by rule and by species (most frequent first). ``suppressed_total`` is
    the number of de-duplicated repeats folded onto the recorded alerts, so a low
    ``total_alerts`` with a high ``suppressed_total`` means "one thing, seen a lot".
    """
    total = len(events)
    suppressed_total = sum(int(e.get("suppressed_count") or 0) for e in events)
    delivered = sum(1 for e in events if e.get("delivery_status") == "delivered")
    skipped = sum(1 for e in events if e.get("delivery_status") == "skipped_severity")

    by_rule: dict[str, int] = {}
    by_species: dict[str, int] = {}
    for e in events:
        rule_name = e.get("rule_name") or "(unnamed rule)"
        by_rule[rule_name] = by_rule.get(rule_name, 0) + 1
        subject = e.get("top_species") or e.get("top_label") or "unknown"
        by_species[subject] = by_species.get(subject, 0) + 1

    return {
        "window": window_label,
        "total_alerts": total,
        "suppressed_total": suppressed_total,
        "delivered": delivered,
        "skipped_by_severity": skipped,
        "by_rule": _ranked(by_rule),
        "by_species": _ranked(by_species),
    }
