# Camtrap DP Direction

ClawCam should preserve enough metadata to export camera-trap data using Camtrap DP-style concepts. Standards-aware design begins in the gateway data model, not at the final export step.

## Mapping Targets

| ClawCam Entity | Standards-Oriented Meaning |
|---|---|
| `Project` | Dataset or project metadata. |
| `Deployment` | Camera deployment at a place and time interval. |
| `Device` | Camera or gateway hardware metadata. |
| `Media` | Image, video, audio, thumbnail, or derived artifact. |
| `Observation` | Ecological observation derived from an event/media record. |
| `Classification` | Human or machine identification with confidence and review state. |

## Export Requirements

Before public export, ClawCam should validate required fields, normalize timestamps, apply privacy rules to sensitive locations, preserve model version metadata, and distinguish machine labels from human-verified labels.

## MVP Scope

The MVP does not need a full Camtrap DP exporter. It does need a data model that will not block a future exporter.
