"""MCP-style gateway tools for ClawCam brain integrations.

These functions are intentionally plain Python callables so they can be wrapped by an
MCP server, an HTTP endpoint, or an Oh-Ben-Claw tool adapter without duplicating
business logic.

Approval policy:
  - get_recent_detections, get_node_health, generate_daily_summary, list_pending_commands:
    read-only, no approval required.
  - capture_now, apply_config_patch:
    approval-gated. The brain enforces human approval before calling these.
    The gateway queues them as pending commands that field nodes can poll.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from clawcam_gateway.ingest.export import export_detections_csv as _export_detections_csv
from clawcam_gateway.storage.database import GatewayDatabase


@dataclass
class ToolContext:
    """Shared context for ClawCam gateway tool calls."""

    database_path: Path | str = "clawcam_gateway.db"
    mqtt_bridge: Optional[Any] = field(default=None, repr=False)  # MQTTBridge | None

    @property
    def db(self) -> GatewayDatabase:
        return GatewayDatabase(self.database_path)

    def publish_command(self, device_id: str, command: dict[str, Any]) -> bool:
        """Push a queued command to the node via MQTT if bridge is active."""
        if self.mqtt_bridge is not None:
            return self.mqtt_bridge.publish_command(device_id, command)
        return False


def get_recent_detections(context: ToolContext, limit: int = 25) -> dict[str, Any]:
    """Return recent detection/event records from the gateway database."""

    safe_limit = max(1, min(int(limit), 100))
    detections = context.db.recent_events(limit=safe_limit)
    return {"ok": True, "limit": safe_limit, "detections": detections}


def get_node_health(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the latest health payload for a device."""

    health = context.db.latest_health(device_id)
    if health is None:
        return {"ok": False, "error": f"no health record found for {device_id}", "device_id": device_id}
    return {"ok": True, "device_id": device_id, "health": health}


def generate_daily_summary(
    context: ToolContext,
    report_date: str | None = None,
    deployment_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Generate a structured summary from recent gateway events."""

    events = context.db.recent_events(limit=max(1, min(int(limit), 500)))
    if report_date:
        events = [event for event in events if event.get("timestamp", "").startswith(report_date)]
    else:
        report_date = date.today().isoformat()
    if deployment_id:
        events = [event for event in events if event.get("deployment_id") == deployment_id]

    event_counts = Counter(event.get("event_type", "unknown") for event in events)
    label_counts: Counter[str] = Counter()
    for event in events:
        for classification in event.get("classifications", []):
            label_counts[classification.get("label", "unknown")] += 1

    # Fold in the day's ecology roll-up (activity + trends + diversity + alert digest).
    from clawcam_gateway.analytics import build_daily_site_section

    day_start = f"{report_date}T00:00:00"
    detections = [
        row
        for row in context.db.list_inference_results(
            limit=5000, deployment_id=deployment_id
        )
        if str(row.get("ran_at", "")).startswith(report_date)
    ]
    alert_events = [
        row
        for row in context.db.list_alert_events(
            limit=5000, deployment_id=deployment_id, since=day_start
        )
        if str(row.get("fired_at", "")).startswith(report_date)
    ]
    site_section = build_daily_site_section(detections, alert_events=alert_events)

    return {
        "ok": True,
        "date": report_date,
        "deployment_id": deployment_id,
        "event_count": len(events),
        "event_counts": dict(event_counts),
        "label_counts": dict(label_counts),
        "summary": _summary_sentence(len(events), event_counts, label_counts),
        "detection_summary": site_section["sentence"],
        "site": site_section["report"],
    }


def list_capabilities(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the ESP-Claw capability groups declared by a node."""

    device = context.db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}
    caps = device.get("capabilities", [])
    return {
        "ok": True,
        "device_id": device_id,
        "capabilities": caps,
        "has_camera_trap": "cap_clawcam_camera_trap" in caps,
        "has_power": "cap_clawcam_power" in caps,
        "has_storage": "cap_clawcam_storage" in caps,
        "has_sensors": "cap_clawcam_sensors" in caps,
        "has_events": "cap_clawcam_events" in caps,
        "has_firmware_ota": "cap_clawcam_firmware_ota" in caps,
    }


def capture_now(context: ToolContext, device_id: str, reason: str | None = None) -> dict[str, Any]:
    """Queue a manual capture command for a ClawCam node.

    The node polls GET /api/v1/commands/{device_id}/pending on each wake cycle
    and executes queued commands. Requires cap_clawcam_camera_trap capability.
    The brain enforces human approval before calling this tool.
    """

    db = context.db
    device = db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}

    caps = device.get("capabilities", [])
    if caps and "cap_clawcam_camera_trap" not in caps:
        return {
            "ok": False,
            "error": f"device {device_id} does not declare cap_clawcam_camera_trap",
            "device_id": device_id,
            "capabilities": caps,
        }

    command_id = f"cmd-capture-{uuid.uuid4().hex[:12]}"
    command = {
        "command_id": command_id,
        "command_type": "capture_now",
        "device_id": device_id,
        "status": "queued",
        "reason": reason or "manual capture requested via brain",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add_pending_command(command)
    mqtt_pushed = context.publish_command(device_id, command)

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "status": "queued",
        "mqtt_pushed": mqtt_pushed,
        "message": "Capture command queued. The node will execute it on its next wake cycle.",
    }


def apply_config_patch(
    context: ToolContext,
    device_id: str,
    patch: dict[str, Any],
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Queue an approved configuration patch for a ClawCam node or gateway.

    The patch is validated and stored as a pending command. The brain enforces
    human approval before calling this tool; approval_id is recorded for audit.
    """

    if not isinstance(patch, dict) or not patch:
        return {
            "ok": False,
            "error": "patch must be a non-empty object",
            "device_id": device_id,
        }

    db = context.db
    device = db.get_device(device_id)
    if device is None:
        return {
            "ok": False,
            "error": f"unknown device: {device_id}",
            "device_id": device_id,
        }

    _validate_config_patch(patch)

    command_id = f"cmd-config-{uuid.uuid4().hex[:12]}"
    command = {
        "command_id": command_id,
        "command_type": "apply_config_patch",
        "device_id": device_id,
        "status": "queued",
        "patch": patch,
        "approval_id": approval_id,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add_pending_command(command)
    mqtt_pushed = context.publish_command(device_id, command)

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "status": "queued",
        "patch_keys": list(patch.keys()),
        "approval_id": approval_id,
        "mqtt_pushed": mqtt_pushed,
        "message": "Config patch queued. The node will apply it on its next wake cycle.",
    }


def list_pending_commands(
    context: ToolContext,
    device_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Return pending commands queued for field nodes."""

    commands = context.db.list_pending_commands(device_id=device_id, status=status)
    return {
        "ok": True,
        "device_id": device_id,
        "status_filter": status,
        "count": len(commands),
        "commands": commands,
    }


def list_firmware_builds(context: ToolContext) -> dict[str, Any]:
    """List all firmware builds uploaded to the gateway."""
    builds = context.db.list_firmware_builds()
    return {"ok": True, "count": len(builds), "builds": builds}


def queue_firmware_update(
    context: ToolContext,
    device_id: str,
    build_id: str,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Queue an OTA firmware update command for a ClawCam node.

    Requires cap_clawcam_firmware_ota capability. The gateway serves the binary
    at a stable download URL embedded in the command payload. The node verifies
    SHA256 before flashing. Approval-gated.
    """
    db = context.db
    device = db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}

    caps = device.get("capabilities", [])
    if caps and "cap_clawcam_firmware_ota" not in caps:
        return {
            "ok": False,
            "error": f"device {device_id} does not declare cap_clawcam_firmware_ota",
            "device_id": device_id,
            "capabilities": caps,
        }

    build = db.get_firmware_build(build_id)
    if build is None:
        return {"ok": False, "error": f"unknown build_id: {build_id}", "build_id": build_id}

    command_id = f"cmd-ota-{uuid.uuid4().hex[:12]}"
    command = {
        "command_id": command_id,
        "command_type": "firmware_update",
        "device_id": device_id,
        "status": "queued",
        "build_id": build_id,
        "version": build["version"],
        "firmware_url": f"/api/v1/firmware/{build_id}/download",
        "sha256": build["sha256"],
        "size_bytes": build["size_bytes"],
        "approval_id": approval_id,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    db.add_pending_command(command)
    mqtt_pushed = context.publish_command(device_id, command)

    return {
        "ok": True,
        "queued": True,
        "command_id": command_id,
        "device_id": device_id,
        "build_id": build_id,
        "version": build["version"],
        "sha256": build["sha256"],
        "status": "queued",
        "mqtt_pushed": mqtt_pushed,
        "message": f"Firmware update to {build['version']} queued. Node will apply on next wake cycle.",
    }


def get_inference_results(context: ToolContext, event_id: str) -> dict[str, Any]:
    """Return species detection results for a specific captured event.

    Inference runs automatically after a node uploads media via the gateway.
    Returns the top detection label, confidence, and full bounding-box list.
    """
    result = context.db.get_inference_result(event_id)
    if result is None:
        return {
            "ok": False,
            "error": f"no inference result found for event {event_id}",
            "event_id": event_id,
        }
    return {"ok": True, "event_id": event_id, "result": result}


def get_activity_report(
    context: ToolContext,
    limit: int = 5000,
    species: str | None = None,
    min_confidence: float = 0.0,
    tz_offset_hours: int = 0,
) -> dict[str, Any]:
    """Per-subject hour-of-day activity + diel pattern over recent detections.

    Answers "when is each species active here?" — returns, per subject, a 24-bucket
    hour-of-day histogram, total count, peak hour, first/last seen, and a diel-pattern
    label (nocturnal / diurnal / crepuscular / cathemeral).

    Arguments
    ---------
    limit:           Max detections to roll up (1–50000, default 5000).
    species:         Substring match on species name (e.g. "deer").
    min_confidence:  Minimum top_confidence to include (default 0.0).
    tz_offset_hours: Shift UTC timestamps to local time for hour-of-day bucketing
                     (e.g. -8 for US Pacific).
    """
    from clawcam_gateway.analytics.activity import build_activity_report

    safe_limit = max(1, min(int(limit), 50_000))
    detections = context.db.list_inference_results(
        limit=safe_limit, species=species, min_confidence=float(min_confidence),
    )
    return {
        "ok": True,
        "report": build_activity_report(detections, tz_offset_hours=int(tz_offset_hours)),
    }


def get_trend_report(
    context: ToolContext,
    limit: int = 5000,
    species: str | None = None,
    min_confidence: float = 0.0,
    tz_offset_hours: int = 0,
) -> dict[str, Any]:
    """Day-over-day detection trends per subject (rising / falling / steady).

    Answers "are sightings increasing here?" — returns, per subject, a total, a trend
    label, the busiest day, first/last day, and a daily time series, plus the overall
    daily totals.

    Arguments mirror ``get_activity_report``: ``limit`` (1–50000), ``species`` substring,
    ``min_confidence``, and ``tz_offset_hours`` (shift UTC to local before bucketing by day).
    """
    from clawcam_gateway.analytics.trends import build_trend_report

    safe_limit = max(1, min(int(limit), 50_000))
    detections = context.db.list_inference_results(
        limit=safe_limit, species=species, min_confidence=float(min_confidence),
    )
    return {
        "ok": True,
        "report": build_trend_report(detections, tz_offset_hours=int(tz_offset_hours)),
    }


def get_site_report(
    context: ToolContext,
    limit: int = 5000,
    min_confidence: float = 0.0,
    tz_offset_hours: int = 0,
    digest_window_s: int = 604800,
) -> dict[str, Any]:
    """One combined site summary — activity + trends + alert digest.

    Answers "what's happening at this site?": a headline (totals, top subject,
    rising/falling species, busiest day, alert counts) plus the full activity, trend, and
    alert-digest sub-reports.

    Arguments
    ---------
    limit:           Max detections to roll up (1–50000, default 5000).
    min_confidence:  Minimum top_confidence to include (default 0.0).
    tz_offset_hours: Shift UTC to local time for day/hour bucketing (e.g. -8).
    digest_window_s: Trailing window for the alert digest (default 604800 = 7 days).
    """
    from datetime import datetime, timedelta, timezone

    from clawcam_gateway.analytics.site import build_site_report

    safe_limit = max(1, min(int(limit), 50_000))
    detections = context.db.list_inference_results(
        limit=safe_limit, min_confidence=float(min_confidence),
    )
    window = max(1, int(digest_window_s))
    since = (datetime.now(timezone.utc) - timedelta(seconds=window)).isoformat()
    alert_events = context.db.list_alert_events(limit=50_000, since=since)
    return {
        "ok": True,
        "report": build_site_report(
            detections, alert_events, tz_offset_hours=int(tz_offset_hours),
            digest_window_label=f"{window}s",
        ),
    }


def get_diversity_report(
    context: ToolContext,
    limit: int = 5000,
    min_confidence: float = 0.0,
) -> dict[str, Any]:
    """Species diversity metrics over recent detections.

    Answers "is this a diverse site or a one-species show?" — returns richness (distinct
    subjects), the Shannon index, Pielou evenness, Simpson dominance, the dominant
    subject, and per-subject counts + proportions.

    Arguments: ``limit`` (1–50000) and ``min_confidence`` (default 0.0).
    """
    from clawcam_gateway.analytics.diversity import build_diversity_report

    safe_limit = max(1, min(int(limit), 50_000))
    detections = context.db.list_inference_results(
        limit=safe_limit, min_confidence=float(min_confidence),
    )
    return {"ok": True, "report": build_diversity_report(detections)}


def get_comparison_report(
    context: ToolContext,
    window_days: int = 7,
    limit: int = 10000,
    min_confidence: float = 0.0,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Compare the last ``window_days`` of detections against the window before it.

    Answers "how does this week compare to last?" — returns totals + percent change,
    subjects newly present (`new_subjects`) or gone (`dropped_subjects`), per-subject
    count deltas sorted by magnitude, the richness delta, whether the dominant subject
    changed, and a one-line headline.

    Arguments
    ---------
    window_days:     Length of each comparison window in days (default 7). The current
                     window is the trailing ``window_days``; the previous window is the
                     ``window_days`` immediately before it.
    limit:           Max detections to fetch across both windows (1–50000, default 10000).
    min_confidence:  Minimum top_confidence to include (default 0.0).
    deployment_id:   Restrict to one deployment (optional).
    """
    from datetime import datetime, timedelta, timezone

    from clawcam_gateway.analytics.compare import build_comparison_report

    from clawcam_gateway.timeutil import parse_ts

    safe_limit = max(1, min(int(limit), 50_000))
    days = max(1, int(window_days))
    now = datetime.now(timezone.utc)
    cur_start = now - timedelta(days=days)
    prev_start = now - timedelta(days=2 * days)

    rows = context.db.list_inference_results(
        limit=safe_limit, min_confidence=float(min_confidence),
        deployment_id=deployment_id,
    )
    # ran_at mixes SQLite ("YYYY-MM-DD HH:MM:SS") and ISO ("...T...+00:00")
    # stamps; string comparison misassigns boundary rows, so parse first.
    current, previous = [], []
    for r in rows:
        ts = parse_ts(r.get("ran_at"))
        if ts is None:
            continue
        if ts >= cur_start:
            current.append(r)
        elif ts >= prev_start:
            previous.append(r)
    return {
        "ok": True,
        "report": build_comparison_report(
            current, previous,
            current_label=f"last {days}d",
            previous_label=f"prior {days}d",
        ),
    }


def get_encounter_report(
    context: ToolContext,
    gap_minutes: int = 30,
    limit: int = 5000,
    min_confidence: float = 0.0,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Independent-encounter counts — collapse lingering captures into events.

    A camera trap fires repeatedly while an animal is in frame, inflating raw detection
    counts. This groups consecutive same-subject detections that are less than
    ``gap_minutes`` apart into one encounter, and reports encounter vs raw counts per
    subject (with a compression ratio) plus the encounter list. Use when you want the
    honest "how many visits?" number rather than "how many frames?".

    Arguments
    ---------
    gap_minutes:    Same-subject detections closer than this join one encounter (default 30).
    limit:          Max detections to consider (1–50000, default 5000).
    min_confidence: Minimum top_confidence to include (default 0.0).
    deployment_id:  Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.encounters import build_encounter_report

    safe_limit = max(1, min(int(limit), 50_000))
    dets = context.db.list_inference_results(
        limit=safe_limit, min_confidence=float(min_confidence), deployment_id=deployment_id,
    )
    return {"ok": True, "report": build_encounter_report(dets, gap_minutes=int(gap_minutes))}


def get_calibration_report(
    context: ToolContext,
    limit: int = 5000,
    buckets: int = 10,
    target_precision: float = 0.9,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Confidence calibration from human review — is the model's confidence trustworthy?

    Uses reviewed detections as ground truth (``verified``/``corrected`` = real hit,
    ``rejected`` = false positive) to measure whether higher confidence means higher
    correctness, and recommends an auto-accept threshold that meets a target precision.
    Answers "can I trust confidence >= X, and what should X be?".

    Arguments
    ---------
    limit:            Max detections to scan for reviewed ones (1–50000, default 5000).
    buckets:          Number of confidence bins for the calibration curve (default 10).
    target_precision: Desired precision for the recommended threshold (default 0.9).
    deployment_id:    Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.calibration import build_calibration_report

    safe_limit = max(1, min(int(limit), 50_000))
    rows = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
    return {
        "ok": True,
        "report": build_calibration_report(
            rows, buckets=int(buckets), target_precision=float(target_precision),
        ),
    }


def get_anomaly_report(
    context: ToolContext,
    limit: int = 5000,
    z_threshold: float = 2.0,
    tz_offset_hours: int = 0,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Flag unusually busy or quiet days in the detection series.

    Scores each day's detection count against the mean and standard deviation of the whole
    series and flags days beyond ``z_threshold`` as spikes (surges) or drops (suspicious
    quiet — a knocked camera, an obstruction). Complements the trend report: trends give
    direction, this catches individual outlier days. Answers "was any day weird?".

    Arguments
    ---------
    limit:           Max detections to scan (1–50000, default 5000).
    z_threshold:     A day is anomalous when ``|z| >= z_threshold`` (default 2.0).
    tz_offset_hours: Shift UTC to local time for day bucketing.
    deployment_id:   Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.anomaly import build_anomaly_report

    safe_limit = max(1, min(int(limit), 50_000))
    dets = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
    return {
        "ok": True,
        "report": build_anomaly_report(
            dets, z_threshold=float(z_threshold), tz_offset_hours=int(tz_offset_hours),
        ),
    }


def get_cooccurrence_report(
    context: ToolContext,
    limit: int = 5000,
    window_minutes: int = 60,
    tz_offset_hours: int = 0,
    min_shared: int = 1,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Score which species use the site at the same times (co-occurrence).

    Bins detections into ``window_minutes`` windows and, for each species pair, reports the
    window Jaccard (how often they coincide) and Schoener's activity overlap (how aligned
    their daily rhythms are). High on both suggests genuine co-use (predator/prey, shared
    resource); high overlap but low Jaccard suggests same schedule with avoidance. Answers
    "which animals show up together here?".

    Arguments
    ---------
    limit:           Max detections to scan (1–50000, default 5000).
    window_minutes:  Co-occurrence bin width in minutes (default 60).
    tz_offset_hours: Shift UTC to local time for the hour-of-day overlap.
    min_shared:      Drop pairs sharing fewer than this many windows (default 1).
    deployment_id:   Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.cooccurrence import build_cooccurrence_report

    safe_limit = max(1, min(int(limit), 50_000))
    dets = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
    return {
        "ok": True,
        "report": build_cooccurrence_report(
            dets, window_minutes=int(window_minutes),
            tz_offset_hours=int(tz_offset_hours), min_shared=int(min_shared),
        ),
    }


def get_abundance_report(
    context: ToolContext,
    limit: int = 5000,
    tz_offset_hours: int = 0,
    trap_days: int | None = None,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Per-species relative abundance index (detections per 100 trap-days).

    Normalises raw counts by survey effort so species are comparable — the camera-trap
    standard for "how much of each animal is here?". Effort defaults to the inclusive
    first→last detection span; pass ``trap_days`` when real camera-active days are known.

    Arguments
    ---------
    limit:           Max detections to scan (1–50000, default 5000).
    tz_offset_hours: Shift UTC to local time for day bucketing.
    trap_days:       Survey effort in camera-active days (optional; estimated if omitted).
    deployment_id:   Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.abundance import build_abundance_report

    safe_limit = max(1, min(int(limit), 50_000))
    dets = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
    return {
        "ok": True,
        "report": build_abundance_report(
            dets, tz_offset_hours=int(tz_offset_hours),
            trap_days=None if trap_days is None else int(trap_days),
        ),
    }


def get_environment_report(
    context: ToolContext,
    limit: int = 1000,
    tz_offset_hours: int = 0,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Environmental telemetry summary — temperature, humidity, pressure over time.

    Reads the promoted environment columns from health records and returns, per quantity,
    the current value, range, mean, trend (rising/falling/steady), and a per-day series.
    Answers "what are conditions at this site, and which way are they heading?".

    Arguments
    ---------
    limit:           Max health readings to scan (1–50000, default 1000).
    tz_offset_hours: Shift UTC to local time for the daily series.
    deployment_id:   Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.environment import build_environment_report

    safe_limit = max(1, min(int(limit), 50_000))
    rows = context.db.environment_series(limit=safe_limit, deployment_id=deployment_id)
    return {
        "ok": True,
        "report": build_environment_report(rows, tz_offset_hours=int(tz_offset_hours)),
    }


def get_weather_activity_report(
    context: ToolContext,
    limit: int = 5000,
    quantity: str = "temperature_c",
    bins: int = 5,
    max_gap_minutes: float = 120.0,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Correlate detection activity with weather — does activity track conditions?

    Aligns each detection to its nearest-in-time environmental reading, bins detections by
    the chosen ``quantity`` (temperature_c / humidity_percent / pressure_hpa), normalizes by
    exposure (readings per bin), and reports the per-bin rate plus a Pearson correlation.

    Arguments
    ---------
    limit:           Max detections and readings to scan each (1–50000, default 5000).
    quantity:        Environmental value to bin by (default temperature_c).
    bins:            Number of equal-width bins (default 5).
    max_gap_minutes: Drop a detection if the nearest reading is further away (default 120).
    deployment_id:   Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.weather_activity import build_weather_activity_report

    safe_limit = max(1, min(int(limit), 50_000))
    dets = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
    rows = context.db.environment_series(limit=safe_limit, deployment_id=deployment_id)
    return {
        "ok": True,
        "report": build_weather_activity_report(
            dets, rows, quantity=str(quantity), bins=int(bins),
            max_gap_minutes=float(max_gap_minutes),
        ),
    }


def get_habitat_report(
    context: ToolContext,
    landcover: dict[str, Any],
    limit: int = 5000,
    top_n: int = 3,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Compare species' habitat use against availability (selection ratio + Ivlev electivity).

    Aligns located detections to a caller-supplied land-cover raster and reports, per class,
    how much it is used versus how much of the survey area it covers. A selection ratio > 1
    means the class is used more than its area predicts (preference); < 1 means avoidance.
    Electivity is the same signal on a bounded −1..+1 scale. Answers 'which habitats do the
    animals here prefer?'. Read-only.

    Arguments
    ---------
    landcover:      Classified raster as a grid — ``origin_lat``, ``origin_lon``, ``step``
                    (cell size in degrees), and ``rows`` (2-D array of class-label strings).
                    ``rows[r][c]`` is the class at lat=origin_lat+r*step, lon=origin_lon+c*step.
    limit:          Max detections to scan (1–50000, default 5000).
    top_n:          How many top species to list per class (default 3).
    deployment_id:  Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.habitat import LandCover, build_habitat_report

    if not isinstance(landcover, dict) or "rows" not in landcover:
        return {"ok": False, "error": "landcover must be an object with origin_lat, origin_lon, step, rows"}
    try:
        lc = LandCover(
            origin_lat=float(landcover["origin_lat"]),
            origin_lon=float(landcover["origin_lon"]),
            step=float(landcover["step"]),
            rows=[[str(c) for c in row] for row in landcover["rows"]],
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"invalid landcover grid: {exc}"}

    safe_limit = max(1, min(int(limit), 50_000))
    dets = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
    return {
        "ok": True,
        "report": build_habitat_report(dets, lc, top_n=int(top_n)),
    }


def run_federated_round(
    context: ToolContext,
    updates: list[dict[str, Any]] | None = None,
    include_local: bool = True,
    node_id: str = "local",
    target_precision: float = 0.9,
    trust: dict[str, float] | None = None,
    previous: dict[str, Any] | None = None,
    limit: int = 5000,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Aggregate federated model updates into the next global model (Conservation Grid G9).

    Federated learning without shipping imagery: each camera node turns its *local
    human-review labels* into a tiny update (a review-grounded confidence threshold + a
    sample count), and a coordinator averages them, sample- and trust-weighted, into a
    versioned global model. Only thresholds and counts move between nodes — never raw
    detections or images.

    This gateway contributes its own local update built from its reviewed detections when
    ``include_local`` is set; pass ``updates`` to fold in peer nodes' updates too. Returns
    ``{version, weights, nodes, total_weight, params}`` plus the contributing node ids.

    Arguments
    ---------
    updates:          Peer-node updates, each ``{node_id, sample_count, weights}`` (optional).
    include_local:    Build + include this gateway's own update from its reviews (default true).
    node_id:          Id for this gateway's local update (default "local").
    target_precision: Precision target for the local threshold (default 0.9).
    trust:            Optional ``{node_id: weight}`` trust multipliers for the aggregate.
    previous:         Prior global model (its ``version`` is incremented); ``None`` = round 1.
    limit:            Max detections to scan for reviewed ones (1–50000, default 5000).
    deployment_id:    Restrict the local update to one deployment (optional).
    """
    from clawcam_gateway.federated import build_local_update, run_federated_round

    ups: list[dict[str, Any]] = list(updates or [])
    if include_local:
        safe_limit = max(1, min(int(limit), 50_000))
        rows = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
        ups.append(build_local_update(str(node_id), rows, target_precision=float(target_precision)))
    if not ups:
        return {"ok": False, "error": "no updates: pass 'updates' or enable 'include_local'"}
    try:
        model = run_federated_round(ups, trust=trust, previous=previous)
    except (ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": f"federated round failed: {exc}"}
    return {
        "ok": True,
        "model": model,
        "contributors": [u.get("node_id") for u in ups],
    }


def get_species_profile(
    context: ToolContext,
    subject: str,
    limit: int = 5000,
    tz_offset_hours: int = 0,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Drill-down profile for a single species: everything about one subject here.

    Composes the analytics suite for one ``subject`` — its abundance (RAI), diel pattern
    and peak hour, trend, independent-encounter count, first/last seen, share of all
    detections, and the species it most often appears alongside. Answers "tell me about
    the coyotes here".

    Arguments
    ---------
    subject:         Species/label to profile (required).
    limit:           Max detections to scan (1–50000, default 5000).
    tz_offset_hours: Shift UTC to local time for activity/abundance bucketing.
    deployment_id:   Restrict to one deployment (optional).
    """
    from clawcam_gateway.analytics.species import build_species_profile

    safe_limit = max(1, min(int(limit), 50_000))
    dets = context.db.list_inference_results(limit=safe_limit, deployment_id=deployment_id)
    return {"ok": True, "report": build_species_profile(
        dets, subject, tz_offset_hours=int(tz_offset_hours))}


def list_sites(context: ToolContext, limit: int = 100) -> dict[str, Any]:
    """List survey-area sites (Conservation Grid geo model).

    Each site carries its boundary polygon, origin, and linked metadata — the
    spatial context detections can be scoped to.
    """
    return {"ok": True, "sites": context.db.list_sites(limit=max(1, min(int(limit), 1000)))}


def get_site_events(
    context: ToolContext,
    site_id: str,
    limit: int = 1000,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Events whose location falls inside a site's boundary polygon.

    Point-in-polygon over the promoted geo columns (indexed bbox prefilter, then
    exact ray-casting). Answers "what was detected inside this survey area?".

    Arguments
    ---------
    site_id:       The site whose boundary scopes the query (required).
    limit:         Max events to scan (1–50000, default 1000).
    deployment_id: Restrict to one deployment (optional).
    """
    safe_limit = max(1, min(int(limit), 50_000))
    events = context.db.events_in_site(site_id, limit=safe_limit, deployment_id=deployment_id)
    return {"ok": True, "site_id": site_id, "count": len(events), "events": events}


def list_device_positions(context: ToolContext, deployment_id: str | None = None) -> dict[str, Any]:
    """List devices that have a known geographic position — the mappable nodes.

    Each entry carries device_id, name, latitude, longitude and deployment_id.
    """
    return {"ok": True, "devices": context.db.devices_with_position(deployment_id=deployment_id)}


def get_site_devices(
    context: ToolContext, site_id: str, deployment_id: str | None = None
) -> dict[str, Any]:
    """Devices whose position falls inside a site's boundary polygon (point-in-polygon).

    Answers "which nodes are deployed inside this survey area?".
    """
    devices = context.db.devices_in_site(site_id, deployment_id=deployment_id)
    return {"ok": True, "site_id": site_id, "count": len(devices), "devices": devices}


def get_review_queue(
    context: ToolContext,
    limit: int = 50,
    low_conf: float = 0.4,
    high_conf: float = 0.75,
    rare_species: list[str] | None = None,
) -> dict[str, Any]:
    """Rank unreviewed detections by how much they need a human look.

    The triage queue surfaces detections still in the ``unreviewed`` state, ordered so the
    ambiguous and the unusual lead: borderline-confidence hits, confident boxes with no
    species ID, and any configured rare species. Confident, identified detections sink to
    the bottom. Read-only; use to decide what to review first.

    Arguments
    ---------
    limit:         Max unreviewed detections to rank (1–1000, default 50).
    low_conf:      Below this confidence a detection is treated as likely noise.
    high_conf:     At/above this confidence a detection is treated as a confident call;
                   the band between the two is the ambiguous zone that most needs review.
    rare_species:  Species names to always bump up for confirmation (optional).
    """
    from clawcam_gateway.inference.triage import build_review_queue
    from clawcam_gateway.storage.database import REVIEW_STATE_UNREVIEWED

    safe_limit = max(1, min(int(limit), 1000))
    rows = context.db.list_inference_results_by_review_state(
        REVIEW_STATE_UNREVIEWED, limit=safe_limit,
    )
    return {
        "ok": True,
        "queue": build_review_queue(
            rows, low_conf=float(low_conf), high_conf=float(high_conf),
            rare_species=rare_species or [],
        ),
    }


def get_fused_detections(
    context: ToolContext,
    event_id: str,
    iou_threshold: float = 0.5,
) -> dict[str, Any]:
    """Fuse an event's detector-chain results into one consolidated detection set.

    The orchestrator stores a fused row at inference time for multi-detector chains;
    when one exists it is returned directly (``stored: true``). For older events (or
    when no fused row exists) fusion is computed at read time: overlapping boxes merge
    into single detections — localisation from the strongest box, the most specific
    label, and species carried over from an overlapping classifier box. Read-only;
    does not modify stored rows.

    Arguments
    ---------
    event_id:      The capture event to fuse detections for.
    iou_threshold: Overlap (0–1) at which two boxes are treated as the same subject
                   (applies to the read-time fallback; a stored fused row used the
                   orchestrator's default).
    """
    from clawcam_gateway.inference.boxops import fuse_detection_groups
    from clawcam_gateway.storage.database import RESULT_ROLE_FUSED

    rows = context.db.list_inference_results_for_event(event_id)
    if not rows:
        return {"ok": False, "error": f"no inference results for event: {event_id}",
                "event_id": event_id}
    members = [r for r in rows if r.get("role") != RESULT_ROLE_FUSED]
    stored_fused = next((r for r in rows if r.get("role") == RESULT_ROLE_FUSED), None)
    if stored_fused is not None:
        return {
            "ok": True,
            "event_id": event_id,
            "stored": True,
            "detectors": [r.get("model_name") for r in members],
            "fused": {
                "detections": stored_fused.get("detections") or [],
                "top_label": stored_fused.get("top_label"),
                "top_confidence": stored_fused.get("top_confidence"),
                "top_species": stored_fused.get("top_species"),
            },
        }
    groups = [r.get("detections") or [] for r in members]
    fused = fuse_detection_groups(groups, iou_threshold=max(0.0, min(1.0, float(iou_threshold))))
    return {
        "ok": True,
        "event_id": event_id,
        "stored": False,
        "detectors": [r.get("model_name") for r in members],
        "fused": fused,
    }


def list_species_detections(
    context: ToolContext,
    limit: int = 25,
    label: str | None = None,
    min_confidence: float = 0.5,
    species: str | None = None,
) -> dict[str, Any]:
    """List recent inference results with optional species/label filtering.

    Useful for asking questions like:
      - "What animals have been detected in the last 24 hours?"
      - "Show me all deer detections with confidence above 0.8"
      - "How many person detections occurred this week?"

    Arguments
    ---------
    limit:          Maximum results to return (1–100, default 25).
    label:          Filter by detection label: "animal", "person", "vehicle".
    min_confidence: Minimum top_confidence score (default 0.5).
    species:        Substring match on species name (e.g. "deer").
    """
    safe_limit = max(1, min(int(limit), 100))
    results = context.db.list_inference_results(
        limit=safe_limit,
        label=label,
        min_confidence=float(min_confidence),
        species=species,
    )
    label_counts: Counter[str] = Counter(
        r["top_label"] for r in results if r["top_label"]
    )
    species_counts: Counter[str] = Counter(
        r["top_species"] for r in results if r["top_species"]
    )
    return {
        "ok": True,
        "count": len(results),
        "label_counts": dict(label_counts),
        "species_counts": dict(species_counts),
        "results": results,
    }


def list_observations_for_review(
    context: ToolContext,
    review_state: str = "needs_review",
    limit: int = 25,
) -> dict[str, Any]:
    """List AI classifications in a given human-review state (triage queue).

    review_state is one of: unreviewed, verified, corrected, rejected,
    needs_review. Useful for "show me everything still waiting on a human" or
    auditing what a model flagged as low-confidence. Read-only.
    """
    from clawcam_gateway.storage.database import REVIEW_STATES

    if review_state not in REVIEW_STATES:
        return {
            "ok": False,
            "error": f"invalid review_state: {review_state!r}",
            "valid": sorted(REVIEW_STATES),
        }
    safe_limit = max(1, min(int(limit), 100))
    results = context.db.list_inference_results_by_review_state(review_state, limit=safe_limit)
    return {
        "ok": True,
        "review_state": review_state,
        "count": len(results),
        "results": results,
    }


def set_review_state(
    context: ToolContext,
    result_id: int,
    review_state: str,
    reviewer: str | None = None,
    note: str | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Set the human-review state on an AI classification. Approval-gated.

    Non-destructive: the original machine detection is preserved; only review
    metadata (state, reviewer, note, reviewed_at) is updated. Human review must
    never overwrite field evidence (DATA_MODEL.md).
    """
    from clawcam_gateway.storage.database import REVIEW_STATES

    if review_state not in REVIEW_STATES:
        return {
            "ok": False,
            "error": f"invalid review_state: {review_state!r}",
            "valid": sorted(REVIEW_STATES),
        }
    try:
        updated = context.db.set_review_state(
            int(result_id), review_state, reviewer=reviewer, note=note
        )
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}
    if updated is None:
        return {"ok": False, "error": f"no classification with result_id {result_id}"}
    return {"ok": True, "updated": True, "result": updated}


def get_cloud_sync_status(
    context: ToolContext,
    limit: int = 25,
    status: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Return cloud upload status for recent media files.

    Shows which images have been successfully synced to cloud storage,
    which are pending, and which failed (with error messages).

    Arguments
    ---------
    limit:    Maximum results to return (1–100, default 25).
    status:   Filter by upload status: "pending", "uploaded", or "failed".
    event_id: Filter to a specific event.
    """
    db = context.db
    safe_limit = max(1, min(int(limit), 100))
    uploads = db.list_cloud_uploads(
        limit=safe_limit,
        status=status,
        event_id=event_id,
    )
    summary = db.get_cloud_upload_summary()
    return {
        "ok": True,
        "summary": summary,
        "count": len(uploads),
        "uploads": uploads,
    }


def export_detections_csv(
    context: ToolContext,
    limit: int = 1000,
    label: str | None = None,
    min_confidence: float = 0.0,
    species: str | None = None,
) -> dict[str, Any]:
    """Export recent inference results as CSV text.

    Returns a CSV-formatted string embedding the detection records so a brain
    or downstream tool can write it to disk or display it inline.

    Arguments
    ---------
    limit:          Maximum rows to export (1–10000, default 1000).
    label:          Filter by detection label: "animal", "person", "vehicle".
    min_confidence: Minimum top_confidence score (default 0.0 = all results).
    species:        Substring match on species name (e.g. "deer").
    """
    safe_limit = max(1, min(int(limit), 10000))
    csv_text = _export_detections_csv(
        context.db,
        limit=safe_limit,
        label=label,
        min_confidence=float(min_confidence),
        species=species,
    )
    row_count = max(0, csv_text.count("\n") - 1)  # subtract header row
    return {
        "ok": True,
        "csv": csv_text,
        "row_count": row_count,
        "filters": {
            "limit": safe_limit,
            "label": label,
            "min_confidence": min_confidence,
            "species": species,
        },
    }


def list_alert_rules(context: ToolContext) -> dict[str, Any]:
    """Return all configured alert rules.

    Alert rules fire webhook notifications when the AI detects matching species,
    labels, or confidence levels. Read-only — creating rules requires approval.
    """
    rules = context.db.list_alert_rules()
    return {"ok": True, "count": len(rules), "rules": rules}


def list_recent_alerts(
    context: ToolContext,
    limit: int = 25,
    rule_id: str | None = None,
    delivery_status: str | None = None,
) -> dict[str, Any]:
    """Return recent fired alert events.

    Each entry shows which rule fired, what was detected, when, and whether
    the webhook delivery succeeded.

    Arguments
    ---------
    limit:           Maximum results to return (1–200, default 25).
    rule_id:         Filter to a specific rule.
    delivery_status: Filter by delivery status: "delivered" or "failed".
    """
    safe_limit = max(1, min(int(limit), 200))
    events = context.db.list_alert_events(
        limit=safe_limit,
        rule_id=rule_id,
        delivery_status=delivery_status,
    )
    return {"ok": True, "count": len(events), "alerts": events}


def create_alert_rule(
    context: ToolContext,
    name: str,
    webhook_url: str | None = None,
    label: str | None = None,
    min_confidence: float = 0.5,
    species_pattern: str | None = None,
    device_id: str | None = None,
) -> dict[str, Any]:
    """Create a new alert rule that fires a webhook on matching detections.

    The rule is stored persistently in the gateway database and evaluated after
    every inference result. Approval-gated — modifies gateway state.

    Arguments
    ---------
    name:            Human-readable name for the rule (required).
    webhook_url:     HTTP(S) endpoint to POST when the rule fires.
                     Falls back to CLAWCAM_ALERT_WEBHOOK_URL if not set.
    label:           Restrict to "animal", "person", or "vehicle". None = any.
    min_confidence:  Minimum top_confidence to fire (default 0.5).
    species_pattern: Case-insensitive substring match on species name.
    device_id:       Only fire for events from this specific device.
    """
    if not name or not name.strip():
        return {"ok": False, "error": "name is required"}

    from clawcam_gateway.alerts.rules import ALERT_LABELS
    if label is not None and label not in ALERT_LABELS:
        return {
            "ok": False,
            "error": f"label must be one of: {', '.join(sorted(ALERT_LABELS))} (got {label!r})",
        }

    safe_confidence = max(0.0, min(float(min_confidence), 1.0))

    rule = {
        "rule_id": f"rule-{uuid.uuid4().hex[:12]}",
        "name": name.strip(),
        "label": label,
        "min_confidence": safe_confidence,
        "species_pattern": species_pattern,
        "device_id": device_id,
        "webhook_url": webhook_url,
        "enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    context.db.add_alert_rule(rule)
    return {
        "ok": True,
        "created": True,
        "rule": rule,
        "message": f"Alert rule '{name}' created. It will fire when detections match the criteria.",
    }


def list_profile_alert_templates(context: ToolContext, profile: str) -> dict[str, Any]:
    """List the recommended alert-rule templates for a device *profile*.

    Read-only preview — does not create anything. Use apply_profile_alert_rules
    to actually seed the rules onto a device.
    """
    from clawcam_gateway.alerts.templates import alert_rule_templates_for_profile
    from clawcam_gateway.profiles import is_valid_profile
    if not is_valid_profile(profile):
        return {"ok": False, "error": f"unknown profile: {profile}"}
    templates = alert_rule_templates_for_profile(profile)
    return {"ok": True, "profile": profile, "count": len(templates), "templates": templates}


def apply_profile_alert_rules(
    context: ToolContext,
    device_id: str,
    enabled: bool = True,
) -> dict[str, Any]:
    """Seed a device with the recommended alert rules for its profile.

    Resolves the device's profile, builds the template rules, and persists one
    alert rule per template (scoped to this device). Approval-gated — creates
    gateway state. Returns the rules that were created (may be empty for
    profiles with no opinionated rules).
    """
    from clawcam_gateway.alerts.templates import alert_rule_templates_for_profile
    from clawcam_gateway.profiles import DEFAULT_PROFILE
    device = context.db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}
    profile = device.get("profile") or DEFAULT_PROFILE
    templates = alert_rule_templates_for_profile(profile)
    created: list[dict[str, Any]] = []
    for t in templates:
        rule = {
            "rule_id": f"rule-{uuid.uuid4().hex[:12]}",
            "name": t["name"],
            "label": t["label"],
            "min_confidence": float(t["min_confidence"]),
            "species_pattern": t["species_pattern"],
            "device_id": device_id,
            "webhook_url": None,
            "enabled": bool(enabled and t.get("enabled", True)),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "required_state": t["required_state"],
        }
        context.db.add_alert_rule(rule)
        created.append(rule)
    return {
        "ok": True,
        "device_id": device_id,
        "profile": profile,
        "created_count": len(created),
        "rules": created,
        "message": f"Seeded {len(created)} alert rule(s) from the '{profile}' profile.",
    }


def list_profiles(context: ToolContext) -> dict[str, Any]:
    """List all available device profiles with their behavioral defaults."""
    from clawcam_gateway.profiles import PROFILES, get_profile_defaults
    return {
        "ok": True,
        "count": len(PROFILES),
        "profiles": [get_profile_defaults(p).to_dict() for p in PROFILES],
    }


def get_device_state(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the profile + state of a device, with deployment-level fallback."""
    row = context.db.get_device_profile_state(device_id)
    if row is None:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}
    deployment_id = row.get("deployment_id") or "default"
    deployment_state = context.db.get_deployment_state(deployment_id)
    effective = row.get("state") or deployment_state or "normal"
    return {
        "ok": True,
        "device_id": device_id,
        "profile": row.get("profile"),
        "state": row.get("state"),
        "deployment_id": deployment_id,
        "deployment_state": deployment_state,
        "effective_state": effective,
    }


def set_device_state(
    context: ToolContext,
    device_id: str,
    state: str,
    reason: str | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Change the runtime state of a device. Approval-gated (changes behavior).

    Allowed states: normal, armed, disarmed, away, vacation, feeding, maintenance.
    Every transition is recorded in the state_transitions audit table.
    """
    from clawcam_gateway.profiles import is_valid_state
    if not is_valid_state(state):
        return {
            "ok": False,
            "error": f"invalid state '{state}'; must be one of "
                     "normal, armed, disarmed, away, vacation, feeding, maintenance",
        }
    ok, prev = context.db.set_device_state(
        device_id, state,
        transitioned_by=approval_id or "mcp_tool",
        reason=reason,
    )
    if not ok:
        return {"ok": False, "error": f"unknown device: {device_id}", "device_id": device_id}
    return {
        "ok": True,
        "device_id": device_id,
        "previous_state": prev,
        "state": state,
        "message": f"Device {device_id} transitioned {prev} → {state}.",
    }


def set_deployment_state(
    context: ToolContext,
    deployment_id: str,
    state: str,
    reason: str | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Change the runtime state of an entire deployment. Approval-gated.

    All devices in the deployment whose own state is unset inherit this value.
    Useful for "arm the whole house" or "switch the apiary to maintenance".
    """
    from clawcam_gateway.profiles import is_valid_state
    if not is_valid_state(state):
        return {"ok": False, "error": f"invalid state '{state}'"}
    ok, prev = context.db.set_deployment_state(
        deployment_id, state,
        transitioned_by=approval_id or "mcp_tool",
        reason=reason,
    )
    if not ok:
        return {"ok": False, "error": f"unknown deployment: {deployment_id}"}
    return {
        "ok": True,
        "deployment_id": deployment_id,
        "previous_state": prev,
        "state": state,
        "message": f"Deployment {deployment_id} transitioned {prev} → {state}.",
    }


def list_state_transitions(
    context: ToolContext,
    target_kind: str | None = None,
    target_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return recent state transitions for diagnostics and audit."""
    safe_limit = max(1, min(int(limit), 500))
    transitions = context.db.list_state_transitions(
        target_kind=target_kind,
        target_id=target_id,
        limit=safe_limit,
    )
    return {"ok": True, "count": len(transitions), "transitions": transitions}


def list_schedules(
    context: ToolContext,
    deployment_id: str | None = None,
    enabled_only: bool = False,
) -> dict[str, Any]:
    """List all schedules (optionally filtered to enabled and/or one deployment)."""
    schedules = context.db.list_schedules(enabled_only=enabled_only, deployment_id=deployment_id)
    return {"ok": True, "count": len(schedules), "schedules": schedules}


def list_schedule_runs(
    context: ToolContext,
    schedule_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Audit log of recent schedule firings."""
    safe_limit = max(1, min(int(limit), 500))
    runs = context.db.list_schedule_runs(
        schedule_id=schedule_id, status=status, limit=safe_limit)
    return {"ok": True, "count": len(runs), "runs": runs}


def create_schedule(
    context: ToolContext,
    name: str,
    action_type: str,
    action_payload: dict[str, Any] | None = None,
    cron_expr: str | None = None,
    starts_at: str | None = None,
    ends_at: str | None = None,
    deployment_id: str = "default",
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Create a scheduled action. Approval-gated — persistent state change.

    Action types:
      set_state, set_deployment_state, enable_rule, disable_rule, webhook.
    Either cron_expr (recurring) or starts_at/ends_at (one-shot window)
    should be provided.
    """
    from clawcam_gateway.scheduler import is_valid_action
    if not name or not name.strip():
        return {"ok": False, "error": "name is required"}
    if not is_valid_action(action_type):
        return {"ok": False, "error": f"invalid action_type: {action_type}"}
    if cron_expr:
        try:
            from croniter import croniter  # type: ignore
            if not croniter.is_valid(cron_expr):
                return {"ok": False, "error": f"invalid cron expression: {cron_expr}"}
        except ImportError:
            return {"ok": False, "error": "croniter not installed; cannot validate cron"}
    schedule_id = f"sched-{uuid.uuid4().hex[:12]}"
    context.db.add_schedule({
        "schedule_id": schedule_id,
        "deployment_id": deployment_id,
        "name": name.strip(),
        "cron_expr": cron_expr,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "action_type": action_type,
        "action_payload": action_payload or {},
        "enabled": True,
    })
    return {
        "ok": True,
        "created": True,
        "schedule": context.db.get_schedule(schedule_id),
        "message": f"Schedule '{name}' created.",
    }


def list_detection_zones(
    context: ToolContext,
    device_id: str | None = None,
    enabled_only: bool = False,
) -> dict[str, Any]:
    """List polygon detection zones, optionally scoped to a device."""
    zones = context.db.list_detection_zones(
        device_id=device_id, enabled_only=enabled_only,
    )
    return {"ok": True, "count": len(zones), "zones": zones}


def create_detection_zone(
    context: ToolContext,
    device_id: str,
    name: str,
    polygon: list[list[float]],
    action: str,
    priority: int = 100,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Create a polygon zone on a camera. Approval-gated (persistent state).

    polygon is a list of [x, y] points in image-normalised coordinates
    (each value 0.0-1.0). action must be one of: alert, record, ignore,
    privacy_mask.
    """
    from clawcam_gateway.zones import is_valid_polygon, is_valid_zone_action
    if not name or not name.strip():
        return {"ok": False, "error": "name is required"}
    if not is_valid_polygon(polygon):
        return {
            "ok": False,
            "error": "polygon must be a list of >=3 [x, y] points with each coord 0-1",
        }
    if not is_valid_zone_action(action):
        return {
            "ok": False,
            "error": f"action must be one of alert, record, ignore, privacy_mask (got {action!r})",
        }
    if context.db.get_device(device_id) is None:
        return {"ok": False, "error": f"unknown device: {device_id}"}
    zone_id = f"zone-{uuid.uuid4().hex[:12]}"
    context.db.add_detection_zone({
        "zone_id": zone_id,
        "device_id": device_id,
        "name": name.strip(),
        "polygon": polygon,
        "action": action,
        "priority": int(priority),
        "enabled": True,
    })
    return {
        "ok": True,
        "created": True,
        "zone": context.db.get_detection_zone(zone_id),
        "message": f"Detection zone '{name}' created on device {device_id}.",
    }


def list_audio_classifications(
    context: ToolContext,
    event_id: str | None = None,
    label: str | None = None,
    species: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return recent audio classifications (BirdNET / glass-break / etc.).

    Audio is captured at devices with profiles that enable it (bird_feeder,
    home_security_*, apiary). Each classifier-hit gets one row with label,
    species, confidence, time offset within the audio file.
    """
    safe_limit = max(1, min(int(limit), 500))
    results = context.db.list_audio_classifications(
        event_id=event_id, label=label, species=species,
        min_confidence=float(min_confidence), limit=safe_limit,
    )
    return {"ok": True, "count": len(results), "results": results}


def get_audio_for_event(context: ToolContext, event_id: str) -> dict[str, Any]:
    """Return all uploaded audio files + their classifications for *event_id*."""
    uploads = context.db.list_audio_uploads(event_id=event_id)
    classifications = context.db.list_audio_classifications(event_id=event_id)
    return {
        "ok": True,
        "event_id": event_id,
        "upload_count": len(uploads),
        "uploads": uploads,
        "classifications": classifications,
    }


def list_detectors(context: ToolContext) -> dict[str, Any]:
    """Return all detectors known to the gateway's registry, with availability."""
    from clawcam_gateway.inference.registry import get_registry
    reg = get_registry()
    return {
        "ok": True,
        "all_detectors": reg.names(),
        "available_detectors": reg.available_names(),
    }


def get_device_detector_chain(context: ToolContext, device_id: str) -> dict[str, Any]:
    """Return the detector chain that will run on uploads from *device_id*.

    Resolution order: per-device override → profile defaults → mock.
    """
    from clawcam_gateway.inference.orchestrator import InferenceOrchestrator
    device = context.db.get_device(device_id)
    if device is None:
        return {"ok": False, "error": f"unknown device: {device_id}"}
    chain = InferenceOrchestrator(db=context.db).chain_for_device(device_id)
    return {
        "ok": True,
        "device_id": device_id,
        "profile": device.get("profile"),
        "chain": chain,
        "override_set": "detector_chain" in device,
    }


def set_device_detector_chain(
    context: ToolContext,
    device_id: str,
    chain: list[str] | None = None,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Set or clear a per-device detector chain override. Approval-gated.

    chain=None resets to profile defaults. List must be detector names from
    the registry (list_detectors); unknown names are stored but will be
    silently skipped by the orchestrator at run-time.
    """
    if chain is not None and not isinstance(chain, list):
        return {"ok": False, "error": "chain must be a list of detector names or null"}
    ok = context.db.set_device_detector_chain(device_id, chain)
    if not ok:
        return {"ok": False, "error": f"unknown device: {device_id}"}
    return {"ok": True, "device_id": device_id, "chain": chain}


def get_event_inference_chain(context: ToolContext, event_id: str) -> dict[str, Any]:
    """Return the full multi-detector chain result for a single event.

    With Phase 12, each event can have multiple inference_results rows
    (one per detector in the chain, plus the stored fused row when 2+
    detectors ran). This tool returns all of them ordered by execution time.
    """
    results = context.db.list_inference_results_for_event(event_id)
    return {"ok": True, "event_id": event_id, "count": len(results), "results": results}


def _validate_config_patch(patch: dict[str, Any]) -> None:
    """Reject patches that reference protected keys."""

    protected = {"device_id", "deployment_id", "firmware", "hardware"}
    bad_keys = protected & set(patch.keys())
    if bad_keys:
        raise ValueError(f"patch must not modify protected keys: {sorted(bad_keys)}")


def _summary_sentence(event_count: int, event_counts: Counter[str], label_counts: Counter[str]) -> str:
    if event_count == 0:
        return "No ClawCam events matched the requested filters."
    common_event = event_counts.most_common(1)[0][0] if event_counts else "event"
    if label_counts:
        common_label, common_label_count = label_counts.most_common(1)[0]
        return f"Found {event_count} event(s), mostly {common_event}; top label is {common_label} ({common_label_count})."
    return f"Found {event_count} event(s), mostly {common_event}; no classifications are available yet."
