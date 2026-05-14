"""Detector abstraction for wildlife image inference.

Hierarchy:
  BaseDetector        — protocol / abstract base
  MockDetector        — deterministic fake results for offline dev and tests
  MegaDetectorV5      — wraps MegaDetector v5 (ultralytics/PyTorch); only
                        instantiated when weights are present on disk

Detection labels follow the MegaDetector convention:
  "animal", "person", "vehicle"

Species classification (from SpeciesNet or fine-tuned heads) adds a
`species` field when available; otherwise it is None.
"""
from __future__ import annotations

import hashlib
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Detection:
    label: str                      # "animal", "person", "vehicle"
    confidence: float               # 0.0–1.0
    bbox: list[float]               # [x1, y1, x2, y2] normalised 0–1
    species: Optional[str] = None   # e.g. "white-tailed deer"; None if unknown


@dataclass
class InferenceResult:
    model_name: str
    model_version: str
    detections: list[Detection] = field(default_factory=list)

    @property
    def top_detection(self) -> Optional[Detection]:
        if not self.detections:
            return None
        return max(self.detections, key=lambda d: d.confidence)

    @property
    def top_label(self) -> Optional[str]:
        td = self.top_detection
        return td.label if td else None

    @property
    def top_confidence(self) -> float:
        td = self.top_detection
        return td.confidence if td else 0.0

    @property
    def top_species(self) -> Optional[str]:
        td = self.top_detection
        return td.species if td else None

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "detections": [
                {
                    "label": d.label,
                    "confidence": round(d.confidence, 4),
                    "bbox": [round(v, 4) for v in d.bbox],
                    "species": d.species,
                }
                for d in self.detections
            ],
            "top_label": self.top_label,
            "top_confidence": round(self.top_confidence, 4),
            "top_species": self.top_species,
        }


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseDetector(ABC):
    @abstractmethod
    def detect(self, image_path: Path) -> InferenceResult:
        """Run inference on an image file and return structured results."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def model_version(self) -> str: ...

    @property
    def is_available(self) -> bool:
        return True


# ── Mock detector (offline dev / tests) ──────────────────────────────────────

_MOCK_ANIMALS = [
    ("animal", "white-tailed deer"),
    ("animal", "raccoon"),
    ("animal", "wild turkey"),
    ("animal", "eastern gray squirrel"),
    ("animal", "coyote"),
    ("animal", None),      # animal detected but species unknown
    ("person", None),
    ("vehicle", None),
]

class MockDetector(BaseDetector):
    """Deterministic fake detector for offline development and testing.

    Seeds randomness from the image path so the same image always produces
    the same result, making tests reproducible.
    """

    def __init__(self, empty_probability: float = 0.15):
        self._empty_prob = empty_probability

    @property
    def model_name(self) -> str:
        return "mock_detector"

    @property
    def model_version(self) -> str:
        return "0.0.0-mock"

    def detect(self, image_path: Path) -> InferenceResult:
        seed = int(hashlib.md5(str(image_path).encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)

        if rng.random() < self._empty_prob:
            return InferenceResult(
                model_name=self.model_name,
                model_version=self.model_version,
                detections=[],
            )

        label, species = rng.choice(_MOCK_ANIMALS)
        confidence = rng.uniform(0.62, 0.98)
        x1 = rng.uniform(0.05, 0.35)
        y1 = rng.uniform(0.05, 0.35)
        x2 = rng.uniform(0.55, 0.92)
        y2 = rng.uniform(0.55, 0.92)

        return InferenceResult(
            model_name=self.model_name,
            model_version=self.model_version,
            detections=[
                Detection(
                    label=label,
                    confidence=round(confidence, 4),
                    bbox=[round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    species=species,
                )
            ],
        )


# ── MegaDetector v5 ───────────────────────────────────────────────────────────

_MD5_LABEL_MAP = {0: "animal", 1: "person", 2: "vehicle"}

class MegaDetectorV5(BaseDetector):
    """MegaDetector v5a/v5b via ultralytics YOLO.

    Lazy-loads the model on first call to avoid import cost when the
    weights file is absent. Falls back gracefully — callers should check
    `is_available` before instantiating, or catch RuntimeError from detect().
    """

    DEFAULT_WEIGHTS_NAME = "md_v5a.0.0.pt"

    def __init__(self, weights_path: Optional[Path] = None, conf_threshold: float = 0.1):
        self._weights_path = weights_path
        self._conf = conf_threshold
        self._model = None
        self._available: Optional[bool] = None

    @property
    def model_name(self) -> str:
        return "MegaDetector"

    @property
    def model_version(self) -> str:
        if self._weights_path:
            return self._weights_path.stem
        return "v5a.0.0"

    @property
    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import ultralytics  # noqa: F401
            wp = self._weights_path or Path(self.DEFAULT_WEIGHTS_NAME)
            self._available = wp.exists()
        except ImportError:
            self._available = False
        return self._available

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.is_available:
            raise RuntimeError(
                "MegaDetector weights not found. "
                f"Download {self.DEFAULT_WEIGHTS_NAME} or set weights_path."
            )
        from ultralytics import YOLO
        wp = self._weights_path or Path(self.DEFAULT_WEIGHTS_NAME)
        self._model = YOLO(str(wp))

    def detect(self, image_path: Path) -> InferenceResult:
        self._load()
        results = self._model.predict(
            str(image_path), conf=self._conf, verbose=False
        )
        detections: list[Detection] = []
        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                label = _MD5_LABEL_MAP.get(cls_id, "unknown")
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxyn[0].tolist()
                detections.append(Detection(
                    label=label,
                    confidence=round(conf, 4),
                    bbox=[round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    species=None,  # MegaDetector v5 detects category, not species
                ))
        return InferenceResult(
            model_name=self.model_name,
            model_version=self.model_version,
            detections=detections,
        )


# ── Factory ───────────────────────────────────────────────────────────────────

def get_detector(weights_path: Optional[Path] = None) -> BaseDetector:
    """Return the best available detector.

    Prefers MegaDetectorV5 when weights are present; falls back to MockDetector
    so the gateway always has a working inference path during development.
    """
    md = MegaDetectorV5(weights_path=weights_path)
    if md.is_available:
        return md
    return MockDetector()
