# ClawCam Samples

This directory contains deterministic Phase 1 sample payloads for gateway, schema, and brain-tool development before real camera hardware is connected.

## Directories

| Directory | Purpose |
|---|---|
| `payloads/` | Hand-authored example device, event, and health payloads. |
| `node-simulator/` | Output location for generated simulator bundles. |
| `media/` | Placeholder location for sample media references. |

## Generate Simulator Payloads

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.simulator.cli --output ../samples/node-simulator
```

## Import Payloads

The gateway import CLI can load sample payloads into a local SQLite database once implemented:

```bash
cd gateway
PYTHONPATH=. python -m clawcam_gateway.ingest.cli import-sample ../samples/payloads --db ../clawcam_gateway.db
```
