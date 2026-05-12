# ClawCam Data Model

ClawCam separates raw device events from ecological observations and human-reviewed classifications. This makes the system auditable and prevents AI-generated labels from overwriting field evidence.

## Core Entities

| Entity | Description | Typical Owner |
|---|---|---|
| `Project` | A monitoring project or deployment campaign. | Gateway/cloud |
| `Deployment` | A camera placement over a time interval, with location, settings, and covariates. | Gateway/cloud |
| `Device` | A node, gateway, or related physical device. | Gateway |
| `Event` | A trigger or operational event, such as PIR motion, scheduled capture, manual capture, low battery, or storage warning. | Node/gateway |
| `Media` | Image, video, audio, thumbnail, or derived media artifact. | Node/gateway/cloud |
| `Observation` | A biological record derived from one or more events/media files. | Gateway/cloud |
| `Classification` | A model or human label with confidence, taxon, model version, and review state. | Gateway/brain/human reviewer |
| `Telemetry` | Battery, storage, environment, radio, uptime, and error metrics. | Node/gateway |
| `ReviewTask` | A workflow item requiring human verification, correction, or approval. | Gateway/brain |

## Schema Files

Initial contracts live in `schemas/`.

| Schema | Purpose |
|---|---|
| `clawcam-device.schema.json` | Describes nodes, gateways, hardware identity, firmware version, capabilities, and deployment links. |
| `clawcam-event.schema.json` | Describes trigger events, capture events, health events, and operational metadata. |
| `clawcam-observation.schema.json` | Describes ecological observations and classifications derived from media/events. |
| `clawcam-health.schema.json` | Describes node/gateway health, battery, storage, radio, and runtime state. |

## Classification Policy

Every AI classification must store the model name, model version, confidence, input media ID, and review state. Human review should create a new classification or update review metadata rather than deleting the original machine output.

| Review State | Meaning |
|---|---|
| `unreviewed` | Produced by a model or node and not yet checked. |
| `verified` | Human accepted the label. |
| `corrected` | Human replaced or refined the label. |
| `rejected` | Human rejected the classification. |
| `needs_review` | Confidence, rarity, policy, or conflict requires review. |

## Standards Direction

The data model should map cleanly to camera-trap standards such as Camtrap DP. ClawCam should preserve enough metadata for later export: project, deployment, device, media, event timestamp, location, classification, taxon, review status, and privacy flags.

## Privacy and Sensitive Data

Sensitive location, rare species, private landowner data, and API credentials must not be published by default. Export and cloud-sync workflows should explicitly filter or transform sensitive fields before release.
