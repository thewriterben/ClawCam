# Camera Health Diagnosis

## Purpose

Diagnose ClawCam node and gateway health problems using telemetry, event history, and deployment context.

## Diagnosis Areas

| Area | Signals |
|---|---|
| Battery | Voltage, percentage, charge state, estimated hours remaining. |
| Storage | Free space, used space, media count, write errors. |
| Connectivity | Last seen, RSSI/SNR, packet loss, sync queue status. |
| Camera | Capture errors, bad image sizes, repeated failures. |
| Clock | Timestamp source, drift, missing RTC/NTP/GPS time. |
| Sensors | Missing or out-of-range environmental values. |

## Output Format

Return a severity-ranked table of issues, likely causes, recommended actions, and whether a field visit is required.
