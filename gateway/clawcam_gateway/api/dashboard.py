"""Minimal local HTML dashboard for the ClawCam gateway."""

from __future__ import annotations

from html import escape
from typing import Any


def render_dashboard(data: dict[str, Any]) -> str:
    """Render a small no-build HTML dashboard from gateway dashboard data."""

    devices = data.get("devices", [])
    events = data.get("recent_events", [])
    health_by_device = data.get("health_by_device", {})

    device_rows = "".join(
        _device_row(device, health_by_device.get(device.get("device_id")))
        for device in devices
    ) or '<tr><td colspan="6">No devices registered yet.</td></tr>'

    event_rows = "".join(_event_row(event) for event in events) or '<tr><td colspan="6">No events ingested yet.</td></tr>'

    label_cards = "".join(
        f'<div class="metric"><span>{escape(str(label))}</span><strong>{count}</strong></div>'
        for label, count in sorted(data.get("label_counts", {}).items())
    ) or '<div class="metric"><span>Labels</span><strong>0</strong></div>'

    event_cards = "".join(
        f'<div class="metric"><span>{escape(str(kind))}</span><strong>{count}</strong></div>'
        for kind, count in sorted(data.get("event_counts", {}).items())
    ) or '<div class="metric"><span>Events</span><strong>0</strong></div>'

    # Inference summary cards
    detection_label_counts = data.get("detection_label_counts", {})
    detection_species_counts = data.get("detection_species_counts", {})
    detection_rows = "".join(
        _detection_row(r) for r in data.get("recent_detections", [])
    ) or '<tr><td colspan="6">No inference results yet.</td></tr>'

    detection_label_cards = "".join(
        f'<div class="metric"><span>{escape(str(label))}</span><strong>{count}</strong></div>'
        for label, count in sorted(detection_label_counts.items())
    ) or '<div class="metric"><span>No detections</span><strong>0</strong></div>'

    top_species = sorted(detection_species_counts.items(), key=lambda x: -x[1])[:5]
    species_rows = "".join(
        f"<tr><td>{escape(sp)}</td><td>{cnt}</td></tr>"
        for sp, cnt in top_species
    ) or "<tr><td>n/a</td><td>0</td></tr>"

    # Cloud sync summary
    cloud_summary = data.get("cloud_summary", {})
    cloud_enabled = data.get("cloud_enabled", False)
    cloud_badge = "ENABLED" if cloud_enabled else "DISABLED"
    cloud_badge_color = "var(--ok)" if cloud_enabled else "var(--muted)"

    cloud_cards = (
        f'<div class="metric"><span>Pending</span><strong style="color:var(--warn)">{cloud_summary.get("pending", 0)}</strong></div>'
        f'<div class="metric"><span>Uploaded</span><strong style="color:var(--ok)">{cloud_summary.get("uploaded", 0)}</strong></div>'
        f'<div class="metric"><span>Failed</span><strong style="color:#ef4444">{cloud_summary.get("failed", 0)}</strong></div>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>ClawCam Gateway Dashboard</title>
  <style>
    :root {{ color-scheme: dark; --bg: #0f172a; --panel: #111827; --muted: #94a3b8; --text: #e5e7eb; --accent: #38bdf8; --ok: #22c55e; --warn: #f59e0b; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: linear-gradient(135deg, #0f172a, #111827); color: var(--text); }}
    header {{ padding: 2rem; border-bottom: 1px solid rgba(148, 163, 184, .25); display: flex; justify-content: space-between; align-items: center; }}
    main {{ padding: 2rem; display: grid; gap: 1.5rem; }}
    h1, h2 {{ margin: 0 0 .75rem; }}
    p {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }}
    .card, table {{ background: rgba(17, 24, 39, .86); border: 1px solid rgba(148, 163, 184, .22); border-radius: 16px; box-shadow: 0 20px 40px rgba(0,0,0,.22); }}
    .card {{ padding: 1rem; }}
    .card h2 {{ display: flex; align-items: center; gap: .5rem; }}
    .metric {{ background: rgba(15, 23, 42, .72); border: 1px solid rgba(148, 163, 184, .18); border-radius: 14px; padding: 1rem; }}
    .metric span {{ display: block; color: var(--muted); font-size: .88rem; }}
    .metric strong {{ display: block; font-size: 2rem; margin-top: .4rem; color: var(--accent); }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
    th, td {{ padding: .8rem; border-bottom: 1px solid rgba(148, 163, 184, .16); text-align: left; vertical-align: top; }}
    th {{ color: #bae6fd; font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; }}
    .status-ok {{ color: var(--ok); font-weight: 700; }}
    .status-warning, .status-critical {{ color: var(--warn); font-weight: 700; }}
    code {{ color: #bae6fd; }}
    .badge {{ font-size: .75rem; font-weight: 700; padding: .2rem .5rem; border-radius: 6px; border: 1px solid; }}
    .export-links {{ display: flex; gap: .75rem; flex-wrap: wrap; margin-top: .5rem; }}
    .export-links a {{ color: var(--accent); font-size: .88rem; text-decoration: none; border: 1px solid rgba(56,189,248,.35); border-radius: 8px; padding: .3rem .7rem; }}
    .export-links a:hover {{ background: rgba(56,189,248,.1); }}
    .refresh-note {{ color: var(--muted); font-size: .8rem; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>ClawCam Gateway Dashboard</h1>
      <p>Gateway <code>{escape(str(data.get("gateway_id", "unknown")))}</code> · {escape(str(data.get("timestamp", "")))}
        <span class="refresh-note"> · auto-refresh 30 s</span>
      </p>
    </div>
    <div class="export-links">
      <a href="/api/v1/export/events.csv">&#x2B73; events.csv</a>
      <a href="/api/v1/export/detections.csv">&#x2B73; detections.csv</a>
    </div>
  </header>
  <main>
    <section class="grid">
      <div class="metric"><span>Registered devices</span><strong>{int(data.get("device_count", 0))}</strong></div>
      <div class="metric"><span>Recent events</span><strong>{int(data.get("event_count", 0))}</strong></div>
      {event_cards}
      {label_cards}
    </section>
    <section class="card">
      <h2>Devices and Health</h2>
      <table>
        <thead><tr><th>Device</th><th>Name</th><th>Status</th><th>Battery</th><th>Storage</th><th>Last Seen</th></tr></thead>
        <tbody>{device_rows}</tbody>
      </table>
    </section>
    <section class="card">
      <h2>Recent Events</h2>
      <table>
        <thead><tr><th>Timestamp</th><th>Event</th><th>Device</th><th>Labels</th><th>Media</th><th>Trigger</th></tr></thead>
        <tbody>{event_rows}</tbody>
      </table>
    </section>
    <section class="card">
      <h2>AI Inference — Recent Detections</h2>
      <div class="grid" style="margin-bottom:1rem">{detection_label_cards}</div>
      <table>
        <thead><tr><th>Event</th><th>Model</th><th>Top Label</th><th>Confidence</th><th>Species</th><th>Ran At</th></tr></thead>
        <tbody>{detection_rows}</tbody>
      </table>
    </section>
    <section class="card">
      <h2>Top Species <span style="color:var(--muted);font-size:.88rem;font-weight:400">(recent detections)</span></h2>
      <table>
        <thead><tr><th>Species</th><th>Detections</th></tr></thead>
        <tbody>{species_rows}</tbody>
      </table>
    </section>
    <section class="card">
      <h2>Cloud Sync
        <span class="badge" style="color:{cloud_badge_color};border-color:{cloud_badge_color}">{cloud_badge}</span>
      </h2>
      <div class="grid">{cloud_cards}</div>
      <p style="margin-top:.75rem">
        Failed uploads can be retried via
        <code>POST /api/v1/cloud/retry</code>.
      </p>
    </section>
  </main>
</body>
</html>"""


def _device_row(device: dict[str, Any], health: dict[str, Any] | None) -> str:
    device_id = escape(str(device.get("device_id", "")))
    name = escape(str(device.get("name", "")))
    status = escape(str((health or {}).get("status", device.get("status", "unknown"))))
    battery = (health or {}).get("battery", {})
    storage = (health or {}).get("storage", {})
    battery_text = "n/a"
    if battery:
        battery_text = f"{battery.get('percentage', 'n/a')}% · {battery.get('voltage', 'n/a')}V"
    storage_text = "n/a"
    if storage:
        storage_text = f"{storage.get('media_count', 0)} media · {storage.get('free_bytes', 'n/a')} free"
    last_seen = escape(str(device.get("last_seen_at") or (health or {}).get("timestamp") or "unknown"))
    return f"<tr><td><code>{device_id}</code></td><td>{name}</td><td class=\"status-{status}\">{status}</td><td>{escape(battery_text)}</td><td>{escape(storage_text)}</td><td>{last_seen}</td></tr>"


def _event_row(event: dict[str, Any]) -> str:
    labels = ", ".join(
        f"{classification.get('label', 'unknown')} ({classification.get('confidence', 'n/a')})"
        for classification in event.get("classifications", [])
    ) or "n/a"
    media = ", ".join(media_item.get("media_id", "unknown") for media_item in event.get("media", [])) or "n/a"
    trigger = event.get("metadata", {}).get("trigger", "n/a")
    return (
        "<tr>"
        f"<td>{escape(str(event.get('timestamp', '')))}</td>"
        f"<td>{escape(str(event.get('event_type', '')))}</td>"
        f"<td><code>{escape(str(event.get('device_id', '')))}</code></td>"
        f"<td>{escape(labels)}</td>"
        f"<td>{escape(media)}</td>"
        f"<td>{escape(str(trigger))}</td>"
        "</tr>"
    )


def _detection_row(result: dict[str, Any]) -> str:
    conf = result.get("top_confidence")
    conf_text = f"{conf:.2f}" if isinstance(conf, (int, float)) else "n/a"
    return (
        "<tr>"
        f"<td><code>{escape(str(result.get('event_id', '')))}</code></td>"
        f"<td>{escape(str(result.get('model_name', '')))}</td>"
        f"<td>{escape(str(result.get('top_label', 'n/a')))}</td>"
        f"<td>{escape(conf_text)}</td>"
        f"<td>{escape(str(result.get('top_species', 'n/a')))}</td>"
        f"<td>{escape(str(result.get('ran_at', '')))}</td>"
        "</tr>"
    )
