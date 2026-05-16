"""AudioPipeline: orchestrates audio_file → classifier(s) → DB rows.

Called as a FastAPI BackgroundTask after an audio file is uploaded.
Never raises — failures log and update the audio_uploads row with an
error column equivalent (status='failed' via classification absence).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from clawcam_gateway.audio.classifier import BaseAudioClassifier, get_default_classifier

if TYPE_CHECKING:
    from clawcam_gateway.storage.database import GatewayDatabase

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Runs configured classifiers against an audio file and writes results.

    Args:
        db:           GatewayDatabase to persist into.
        classifier:   Single classifier instance, or None to use the
                      default factory (BirdNET when available, else Mock).
        enabled:      Master toggle. When False, classify() is a no-op.
    """

    def __init__(
        self,
        db: "GatewayDatabase",
        classifier: BaseAudioClassifier | None = None,
        enabled: bool = True,
    ):
        self._db = db
        self._enabled = enabled
        self._classifier = classifier or get_default_classifier()

    @property
    def classifier_name(self) -> str:
        return self._classifier.name

    def run(self, audio_id: int, audio_path: str | Path,
            event_id: str | None = None) -> int:
        """Score the audio file at *audio_path* and persist all hits.

        Returns the number of classifications stored. Never raises.
        """
        if not self._enabled:
            return 0
        try:
            classifications = self._classifier.classify(audio_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AudioPipeline: classifier %s raised: %s",
                            self._classifier.name, exc)
            return 0

        stored = 0
        for c in classifications:
            try:
                self._db.add_audio_classification({
                    "audio_id": audio_id,
                    "event_id": event_id,
                    "classifier_name": self._classifier.name,
                    "classifier_version": self._classifier.version,
                    "label": c.label,
                    "species": c.species,
                    "confidence": c.confidence,
                    "time_offset_s": c.time_offset_s,
                    "duration_s": c.duration_s,
                })
                stored += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("AudioPipeline: failed to store classification: %s", exc)
        return stored
