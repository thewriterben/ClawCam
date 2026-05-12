# ClawCam Model Registry

This directory tracks model integrations and deployment notes. Models should be versioned and auditable. Classification records must store model name, version, runtime, confidence, and review state.

## Model Tiers

| Tier | Runtime | Purpose |
|---|---|---|
| Gateway detection/classification | Raspberry Pi, Jetson, mini PC | SpeciesNet, MegaDetector-style detection, and larger wildlife models. |
| MCU filtering | ESP32-S3/P4 | Lightweight empty/animal/person/simple-class filtering using ESP-DL or LiteRT Micro. |
| Cloud/research | Optional cloud backend | Large batch analysis, re-identification, long-term model evaluation. |

## Directories

| Directory | Purpose |
|---|---|
| `speciesnet/` | Notes and adapters for SpeciesNet-style species classification. |
| `megadetector/` | Notes and adapters for detection-first camera-trap workflows. |
| `espdl/` | ESP-DL model conversion and deployment notes. |

## Policy

Do not commit large model weights without a clear license and storage strategy. Prefer documented download scripts, checksums, and model cards.
