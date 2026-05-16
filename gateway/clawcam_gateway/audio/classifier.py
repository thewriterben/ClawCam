"""Audio classifier abstraction + Mock implementation.

Same shape as ``inference.detector``: an abstract ``BaseAudioClassifier``
returns a list of ``AudioClassification`` dataclasses; concrete classes
plug in BirdNET, YAMNet (glass-break, gunshot, scream), or any future
audio model. ``MockAudioClassifier`` ships deterministic seeded results
so CI and integration tests don't depend on model weight availability.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AudioClassification:
    """One classifier-emitted hit within an audio file.

    Mirrors the visual ``Detection`` shape so downstream code (alerts,
    schedules, MCP tools) doesn't have to learn a different vocabulary.
    """

    label: str                       # "bird", "glass_break", "gunshot", "scream", ...
    confidence: float                # 0.0–1.0
    time_offset_s: float = 0.0       # When in the file this hit occurs
    duration_s: float = 0.0          # Length of the matching segment
    species: str | None = None       # e.g. "Black-capped Chickadee"; None if N/A

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "time_offset_s": self.time_offset_s,
            "duration_s": self.duration_s,
            "species": self.species,
        }


class BaseAudioClassifier(ABC):
    """Abstract audio classifier interface."""

    name: str = "base"
    version: str = "0.0.0"

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this classifier can actually score audio.

        Heavy classifiers (BirdNET) should return False when model
        weights are missing so the pipeline falls back to mocks.
        """

    @abstractmethod
    def classify(self, audio_path: str | Path) -> list[AudioClassification]:
        """Score *audio_path* and return zero or more classifications."""


class MockAudioClassifier(BaseAudioClassifier):
    """Deterministic seeded fake classifier — always available.

    Hashes the file contents (or just the filename if unreadable) and
    uses the digest to pick a stable species + confidence value. This
    makes tests reproducible without external model dependencies.
    """

    name = "mock_audio_classifier"
    version = "0.0.0-mock"

    _CATALOG: list[tuple[str, str | None]] = [
        ("bird", "American Robin"),
        ("bird", "Black-capped Chickadee"),
        ("bird", "Northern Cardinal"),
        ("bird", "House Finch"),
        ("dog_bark", None),
        ("vehicle", None),
        ("glass_break", None),
        ("scream", None),
    ]

    def __init__(self, empty_probability: float = 0.1):
        self._empty_probability = empty_probability

    @property
    def is_available(self) -> bool:
        return True

    def classify(self, audio_path: str | Path) -> list[AudioClassification]:
        path = Path(audio_path)
        try:
            payload = path.read_bytes() if path.exists() else path.name.encode()
        except Exception:  # noqa: BLE001
            payload = path.name.encode()
        digest = hashlib.sha256(payload).digest()

        # First byte selects empty vs populated.
        empty_threshold = int(self._empty_probability * 256)
        if digest[0] < empty_threshold:
            return []

        # Next byte selects entry; next two encode confidence and offset.
        label, species = self._CATALOG[digest[1] % len(self._CATALOG)]
        confidence = 0.5 + (digest[2] / 255.0) * 0.5     # 0.5–1.0
        time_offset = (digest[3] / 255.0) * 5.0           # 0–5 s
        duration = 1.0 + (digest[4] / 255.0) * 2.0        # 1–3 s

        return [
            AudioClassification(
                label=label,
                confidence=round(confidence, 3),
                time_offset_s=round(time_offset, 3),
                duration_s=round(duration, 3),
                species=species,
            )
        ]


def get_default_classifier() -> BaseAudioClassifier:
    """Return the best available audio classifier (BirdNET > Mock)."""
    try:
        from clawcam_gateway.audio.birdnet import BirdNETClassifier
        candidate = BirdNETClassifier()
        if candidate.is_available:
            return candidate
    except Exception as exc:  # noqa: BLE001 - BirdNET is optional
        logger.debug("BirdNET unavailable, falling back to mock: %s", exc)
    return MockAudioClassifier()
