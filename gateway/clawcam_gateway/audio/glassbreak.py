"""Acoustic alarm-event classifier (indoor-security profile).

Detects security-relevant sounds — glass breaking, alarms/sirens, screams,
gunshots — using a YAMNet (AudioSet) model and maps its 521 AudioSet classes
down to ClawCam's audio vocabulary (``glass_break``, ``alarm``, ``scream``,
``gunshot``).

Design / offline-first
----------------------
The model stack (``tensorflow`` + ``tensorflow_hub`` + an audio loader) is an
optional, lazy dependency: ``is_available`` is ``False`` until those import, so
the audio pipeline falls back to other classifiers (or the mock) in CI and on
gateways without the model. Install with::

    pip install "clawcam-gateway[audio]"

``tensorflow_hub.load`` fetches/caches the YAMNet model on first use, so a field
gateway needs that one-time download (or a pre-seeded TFHub cache).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from clawcam_gateway.audio.classifier import AudioClassification, BaseAudioClassifier

logger = logging.getLogger(__name__)

YAMNET_HANDLE = "https://tfhub.dev/google/yamnet/1"
_TARGET_SAMPLE_RATE = 16000

# YAMNet AudioSet display-name -> ClawCam label.
_YAMNET_LABEL_MAP: dict[str, str] = {
    "Glass": "glass_break",
    "Shatter": "glass_break",
    "Breaking": "glass_break",
    "Alarm": "alarm",
    "Smoke detector, smoke alarm": "alarm",
    "Fire alarm": "alarm",
    "Siren": "alarm",
    "Civil defense siren": "alarm",
    "Screaming": "scream",
    "Shout": "scream",
    "Yell": "scream",
    "Gunshot, gunfire": "gunshot",
    "Machine gun": "gunshot",
}


def map_audio_event(yamnet_label: str) -> str | None:
    """Map a YAMNet display name to a ClawCam audio label, or None if not security-relevant."""
    return _YAMNET_LABEL_MAP.get(yamnet_label)


class GlassBreakClassifier(BaseAudioClassifier):
    """YAMNet-backed alarm-event classifier (glass break, alarm, scream, gunshot)."""

    name = "yamnet_alarm"
    version = "0.1.0"

    def __init__(self, min_confidence: float = 0.40, model_handle: str = YAMNET_HANDLE):
        self._min_confidence = min_confidence
        self._model_handle = model_handle
        self._model: Any = None
        self._class_names: list[str] | None = None

    @property
    def is_available(self) -> bool:
        try:
            import tensorflow  # noqa: F401
            import tensorflow_hub  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        # Need at least one audio loader.
        try:
            import librosa  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            try:
                import soundfile  # noqa: F401
                return True
            except Exception:  # noqa: BLE001
                return False

    def _load_model(self) -> None:
        if self._model is not None:
            return
        import csv

        import tensorflow_hub as hub

        self._model = hub.load(self._model_handle)
        class_map_path = self._model.class_map_path().numpy().decode("utf-8")
        with open(class_map_path) as f:
            self._class_names = [row["display_name"] for row in csv.DictReader(f)]

    def _load_audio(self, audio_path: str | Path):
        """Return a mono 16 kHz float32 waveform."""
        try:
            import librosa

            wav, _ = librosa.load(str(audio_path), sr=_TARGET_SAMPLE_RATE, mono=True)
            return wav
        except Exception:  # noqa: BLE001 - fall back to soundfile + naive resample
            import numpy as np
            import soundfile as sf

            wav, sr = sf.read(str(audio_path), dtype="float32")
            if getattr(wav, "ndim", 1) > 1:
                wav = wav.mean(axis=1)
            if sr != _TARGET_SAMPLE_RATE:
                n = int(len(wav) * _TARGET_SAMPLE_RATE / sr)
                wav = np.interp(
                    np.linspace(0, len(wav), n, endpoint=False),
                    np.arange(len(wav)),
                    wav,
                ).astype("float32")
            return wav

    def classify(self, audio_path: str | Path) -> list[AudioClassification]:
        if not self.is_available:
            return []
        try:
            self._load_model()
            import numpy as np

            waveform = self._load_audio(audio_path)
            scores, _embeddings, _spectrogram = self._model(waveform)
            mean_scores = np.mean(scores.numpy(), axis=0)  # per-class mean over frames
        except Exception as exc:  # noqa: BLE001 - never abort the pipeline
            logger.warning("GlassBreakClassifier failed on %s: %s", audio_path, exc)
            return []

        assert self._class_names is not None
        # Aggregate AudioSet classes that map to the same ClawCam label, keeping the max.
        best: dict[str, float] = {}
        for idx, score in enumerate(mean_scores):
            if idx >= len(self._class_names):
                break
            label = map_audio_event(self._class_names[idx])
            if label is None:
                continue
            conf = float(score)
            if conf >= self._min_confidence and conf > best.get(label, 0.0):
                best[label] = conf

        return [
            AudioClassification(label=label, confidence=round(conf, 3), duration_s=0.0)
            for label, conf in sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        ]
