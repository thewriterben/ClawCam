# ClawCam Detection Analytics

This document is the reference for the detection-analytics suite: the read-only reports
the gateway computes over stored detections, how each is exposed (REST endpoint + MCP
tool), and the question each one answers. It complements the raw data tools
(`get_recent_detections`, `list_species_detections`, the review-state tools) by turning
detection rows into the numbers an operator — or the Oh-Ben-Claw brain — actually reasons
about.

## At a glance

| Report | Builder (`analytics/…`) | MCP tool | REST endpoint | Answers |
|---|---|---|---|---|
| Activity | `build_activity_report` | `get_activity_report` | `GET /api/v1/analytics/activity` | *When* is each species active? (hour-of-day + diel pattern) |
| Trends | `build_trend_report` | `get_trend_report` | `GET /api/v1/analytics/trends` | *How are the rates changing* — who's rising/falling? |
| Diversity | `build_diversity_report` | `get_diversity_report` | `GET /api/v1/analytics/diversity` | *How diverse* is the site — one species or many? |
| Encounters | `build_encounter_report` | `get_encounter_report` | `GET /api/v1/analytics/encounters` | *How many real visits* (not frames)? |
| Comparison | `build_comparison_report` | `get_comparison_report` | `GET /api/v1/analytics/comparison` | *How does this week compare to last?* |
| Calibration | `build_calibration_report` | `get_calibration_report` | `GET /api/v1/analytics/calibration` | *Can I trust the model's confidence, and at what threshold?* |
| Anomaly | `build_anomaly_report` | `get_anomaly_report` | `GET /api/v1/analytics/anomalies` | *Was any day unusually busy or quiet?* |
| Site | `build_site_report` | `get_site_report` | `GET /api/v1/analytics/site` | *What's happening at this site?* (composes the above) |
| Fused detections | `inference/boxops.py` | `get_fused_detections` | — (MCP only) | *What is actually in this capture?* (merge a detector chain) |
| Review queue | `inference/triage.py` | `get_review_queue` | — (MCP only) | *What should a human review first?* |

Every report is **read-only** and **auto-approved** in the brain adapter — they observe,
they never actuate.

## The reports

**Activity** buckets each subject's detections into a 24-slot hour-of-day histogram and
labels the diel pattern (`nocturnal` / `diurnal` / `crepuscular` / `cathemeral`), with a
peak hour and first/last-seen. `tz_offset_hours` shifts UTC to local time for honest
hour-of-day bucketing.

**Trends** buckets detections by calendar day and classifies each subject as `rising`,
`falling`, or `steady` by comparing the mean daily rate of the earlier vs later half of
the window (mean-of-halves, so it isn't fooled by an odd split), plus the busiest day.

**Diversity** reports standard ecology metrics: richness (distinct subjects), the Shannon
index, Pielou evenness, Simpson dominance, and the dominant subject.

**Encounters** collapses lingering captures into *independent detection events*:
consecutive same-subject detections closer than `gap_minutes` (default 30) count as one
visit. It reports encounter-vs-raw counts per subject with a compression ratio — the
honest "how many visits?" number instead of "how many frames?".

**Comparison** takes a current window and the equal window before it and returns totals +
percent change, newly-present (`new_subjects`) vs vanished (`dropped_subjects`) subjects,
per-subject deltas sorted by magnitude, a richness delta, and whether the dominant subject
changed. The `get_comparison_report` tool splits a single fetch into the two windows by
`window_days`.

**Calibration** uses human review as ground truth (`verified`/`corrected` = real hit,
`rejected` = false positive) to measure whether higher confidence means higher correctness
(`well_calibrated`) and to recommend a `suggested_threshold` — the lowest confidence at
which accepting everything above it still meets `target_precision`. Empty of reviewed
rows, it returns a clear "nothing to calibrate on" message.

**Anomaly** z-scores each day's detection count against the series mean/stdev and flags
days beyond `z_threshold` (default 2.0) as `spike` (a surge) or `drop` (a suspicious quiet
— a knocked camera, an obstruction). A flat series or fewer than two days yields no
false anomalies.

**Site** is the composition: one call returns a `headline` (total detections, total
encounters, distinct subjects, top subject, rising/falling, busiest day, richness,
evenness, alert counts) plus the full `activity`, `trends`, `diversity`, `encounters`, and
`alerts` sub-reports. It is the single "what's happening here?" answer.

**Fused detections** (`get_fused_detections`) returns an event's consolidated detection
set — localisation from the strongest box, the most specific label, and species carried
over from an overlapping classifier. Since the orchestrator-fusion change, fusion happens
**at inference time**: when a chain stores 2+ detector results, the orchestrator persists
one `role='fused'` row and demotes the raw per-detector rows to `role='chain_member'`
(replace-not-add — default listings, analytics, and the review queue see only the fused
row, so a chain counts each subject once; the raw rows are preserved as field evidence in
the per-event chain view). The tool returns the stored fused row when present
(`stored: true`) and falls back to read-time fusion for older events. The underlying
`boxops` module provides `iou`, `nms`, and `merge_results` for reuse.

**Review queue** (`get_review_queue`) ranks unreviewed detections by attention-needed:
borderline-confidence hits, confident boxes with no species ID, and configured rare
species lead; confident identified detections sink.

## Composition & propagation

The site report composes the individual builders, and `build_daily_site_section`
(used by `generate_daily_summary`) composes the site report. So the daily summary
automatically carries the day's activity, trends, diversity, encounters, and alert digest
— add a metric to the site report and it flows to the daily summary for free. The
scheduler's `daily_summary` action delivers that whole picture to a webhook on a cron.

## Design conventions

Each report is a **pure, storage-agnostic builder** in `analytics/` (or `inference/` for
box-ops and triage): it takes already-fetched detection dicts and returns a
JSON-serialisable result with **no database or framework imports**. This keeps the logic
unit-testable in isolation — the tests import only the builder module (stdlib-level
dependencies), so they run without standing up the DB or the FastAPI app.

Each report is surfaced through the tool-catalog **single source of truth**, wired at six
points:

1. the tool function in `tools/clawcam_tools.py` (fetches rows, calls the builder),
2. the import + `__all__` in `tools/__init__.py`,
3. the import + dispatch mapping in `mcp_server/tool_dispatch.py`,
4. the `TOOL_DEFINITIONS` entry in `mcp_server/stdio_server.py`,
5. the `auto_approve` set in `brain/oh-ben-claw-adapter/clawcam_adapter.py`,
6. the REST endpoint in `api/app.py` (where applicable).

`test_tool_catalog_ssot.py` guards that these stay in lockstep.

## Front end

`dashboards/detection-dashboard.html` is a single self-contained page (no gateway
changes) that polls `/analytics/site`, `/calibration`, and `/anomalies` and renders stat
cards, a trends panel, diversity + calibration, a daily-volume bar chart with anomalies
highlighted, and per-subject hour-of-day activity histograms. Configure the gateway URL,
token, and TZ offset in the header; it persists them and auto-refreshes.

## Running the tests

All from the `gateway/` directory with the venv active (see `gateway/pyproject.toml` for
the `pytest` config; `pythonpath = ["."]` is why the package imports resolve from there):

```
cd gateway
.venv/Scripts/Activate.ps1      # Windows PowerShell
python -m pytest ../tests/gateway -q
```

The pure analytics tests (`test_activity_report.py`, `test_trend_report.py`,
`test_diversity_report.py`, `test_encounter_report.py`, `test_comparison_report.py`,
`test_calibration_report.py`, `test_anomaly_report.py`, `test_site_report.py`,
`test_boxops.py`, `test_triage.py`) import only their builder module and need no runtime
dependencies; the tool- and API-level tests exercise the DB and FastAPI paths.
