"""BirdNET integration stub.

BirdNET-Analyzer (https://github.com/kahst/BirdNET-Analyzer) is the
field-standard bird-call ID model from the Cornell Lab of Ornithology.
This module wraps ``birdnetlib`` (the maintained Python wrapper) behind
``BaseAudioClassifier`` so the rest of the pipeline never imports it
directly. The import is lazy: when ``birdnetlib`` isn't installed, the
class reports ``is_available = False`` and ``classify()`` is a no-op.

Production deployments add::

    pip install birdnetlib tflite-runtime

The model weights are bundled with ``birdnetlib`` so no extra download
step is required. Latitude / longitude / week-of-year hints are pulled
from the ClawCam gateway config to bias the classifier toward species
that are actually likely to be present.
"""

from __future__ import annotations

import logging
from pathlib import Path

from clawcam_gateway.audio.classifier import AudioClassification, BaseAudioClassifier

logger = logging.getLogger(__name__)


class BirdNETClassifier(BaseAudioClassifier):
    """Wraps ``birdnetlib.Analyzer`` when available; no-op otherwise."""

    name = "birdnet_analyzer"
    version = "2.4"

    def __init__(self, latitude: float | None = None, longitude: float | None = None,
                 min_confidence: float = 0.25):
        self._latitude = latitude
        self._longitude = longitude
        self._min_confidence = min_confidence
        self._analyzer = None
        try:
            from birdnetlib.analyzer import Analyzer  # type: ignore
            self._analyzer = Analyzer()
        except ImportError:
            logger.debug("birdnetlib not installed; BirdNETClassifier disabled")
        except Exception as exc:  # noqa: BLE001
            logger.warning("BirdNET initialisation failed: %s", exc)

    @property
    def is_available(self) -> bool:
        return self._analyzer is not None

    def classify(self, audio_path: str | Path) -> list[AudioClassification]:
        if self._analyzer is None:
            return []
        try:
            from birdnetlib import Recording  # type: ignore
        except ImportError:
            return []
        try:
            recording = Recording(
                self._analyzer, str(audio_path),
                lat=self._latitude, lon=self._longitude,
                min_conf=self._min_confidence,
            )
            recording.analyze()
            out: list[AudioClassification] = []
            for det in recording.detections:
                # birdnetlib yields {"common_name": ..., "scientific_name": ...,
                # "start_time": ..., "end_time": ..., "confidence": ...}
                out.append(AudioClassification(
                    label="bird",
                    species=det.get("scientific_name") or det.get("common_name"),
                    confidence=float(det.get("confidence", 0.0)),
                    time_offset_s=float(det.get("start_time", 0.0)),
                    duration_s=float(det.get("end_time", 0.0)) - float(det.get("start_time", 0.0)),
                ))
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("BirdNET classify failed: %s", exc)
            return []
