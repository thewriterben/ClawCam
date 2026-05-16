"""Audio capture, storage, and classification for ClawCam gateway.

Audio is a first-class media modality alongside JPEG image capture. It
enables product modules that don't work with vision alone:

  - **Bird ID**: BirdNET classifies bird calls captured at feeder stations.
  - **Home security**: glass-break, gunshot, scream, dog-bark detection.
  - **Wildlife research**: nocturnal call surveys, distress vocalisations.

The data model mirrors the image inference pipeline:

  audio_uploads     ← one row per uploaded WAV / OGG / MP3 file
  audio_classifications ← N rows per audio file (one per classifier-hit)

Classifiers implement the ``BaseAudioClassifier`` abstract interface.
``MockAudioClassifier`` is the always-available, deterministic stub used
in CI; ``BirdNETClassifier`` lazy-imports ``birdnetlib`` and falls back
to a no-op when the model weights aren't available.
"""

from clawcam_gateway.audio.classifier import (
    AudioClassification,
    BaseAudioClassifier,
    MockAudioClassifier,
    get_default_classifier,
)
from clawcam_gateway.audio.pipeline import AudioPipeline

__all__ = [
    "AudioClassification",
    "AudioPipeline",
    "BaseAudioClassifier",
    "MockAudioClassifier",
    "get_default_classifier",
]
