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
| `speciesnet/` *(planned)* | Notes and adapters for SpeciesNet-style species classification. |
| `megadetector/` *(planned)* | Drop MegaDetector weights here or set `CLAWCAM_INFERENCE_WEIGHTS`. |
| `espdl/` *(planned)* | ESP-DL model conversion and deployment notes. |

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

## License-plate OCR (`plate_ocr`)

The `plate_ocr` detector (`gateway/clawcam_gateway/inference/plate_ocr.py`) refines a
MegaDetector `vehicle` hit by reading the license plate into the detection's
`species` field, for the driveway and outdoor-security profiles. It is
**availability-gated** on the OCR engine: until `easyocr` is installed
(`pip install "clawcam-gateway[ocr]"`) the detector reports unavailable and the
orchestrator skips it.

`easyocr` downloads its recognition models on first use, so a field gateway needs
that one-time fetch (or a pre-seeded `~/.EasyOCR` cache). For best accuracy a
production setup should crop to the vehicle bounding box before OCR; the scaffold
OCRs the whole frame and filters for plate-shaped tokens. Validate on-device in
the Phase 14 field test.

## Face recognition (`face_recognizer`)

The `face_recognizer` detector (`gateway/clawcam_gateway/inference/face_recognizer.py`)
refines a MegaDetector `person` hit by locating faces and tagging the detection's
`species` field with a recognised name (or `unknown`), for the home-security
profiles. It is **availability-gated** on the engine: until `face_recognition` is
installed (`pip install "clawcam-gateway[faces]"`) the detector reports
unavailable and the orchestrator skips it.

Enroll identities by placing `known_faces/<name>.jpg` in this directory (filename
stem = person name); with no enrollment, faces are detected but reported as
`unknown`. **Privacy:** this is biometric processing — pair it with `privacy_mask`
zones and confirm it is lawful for your deployment before enabling. Encodings are
computed locally; no image leaves the device. Validate on-device in the Phase 14
field test.

## Acoustic alarm events (`glass_break` / YAMNet)

The `GlassBreakClassifier` (`gateway/clawcam_gateway/audio/glassbreak.py`) is an
**audio** classifier (not a visual detector) for the indoor-security profile. It
runs YAMNet over an uploaded clip and maps AudioSet classes to ClawCam labels:
`glass_break`, `alarm`, `scream`, `gunshot`. It is **availability-gated** on the
model stack — until `pip install "clawcam-gateway[audio]"` (tensorflow,
tensorflow-hub, soundfile) the audio pipeline falls back to BirdNET/mock.

`tensorflow_hub.load` caches the YAMNet model on first use (one-time download).
`get_default_classifier()` composes every available real audio classifier
(BirdNET species ID + YAMNet alarm events) via `CompositeAudioClassifier`, so a
single clip can yield both bird species and alarm-event hits; with no models
installed it returns the deterministic mock. Validate on-device in the Phase 14
field test.
