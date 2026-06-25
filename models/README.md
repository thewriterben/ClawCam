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

## Bird species classifier (`bird_classifier`)

The `bird_classifier` detector (`gateway/clawcam_gateway/inference/bird_classifier.py`)
refines a MegaDetector `animal` hit into a bird species for the bird-feeder and
hummingbird profiles. It is **availability-gated**: until both files below exist
(and `torch` + `pillow` are installed, e.g. `pip install "clawcam-gateway[vision]"`),
the detector reports unavailable and the orchestrator skips it — so CI and
model-less field gateways are unaffected.

To activate it, drop these into this directory (or set `CLAWCAM_MODELS_DIR`):

| File | Contents |
|---|---|
| `bird_classifier.torchscript.pt` | A TorchScript image classifier taking a normalised `[1,3,224,224]` tensor (ImageNet mean/std) and returning class logits `[1,N]`. |
| `bird_classifier_labels.txt` | `N` species names, one per line, in class-index order. |

Any model matching that contract works — a fine-tuned timm/torchvision head, or a
NABirds / iNaturalist-trained classifier. Record model name, version, and
confidence per the model-registry rules above. Validate on-device as part of the
Phase 14 field test (see `docs/PHASE14_FIELD_TEST_PLAN.md`).
