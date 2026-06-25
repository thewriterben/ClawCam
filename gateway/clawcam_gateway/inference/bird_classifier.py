"""Fine-grained bird species classifier (bird-feeder / hummingbird profiles).

This refines a coarse MegaDetector "animal" hit into a bird species. It runs an
image-classification model over the frame and emits a single ``animal``
``Detection`` whose ``species`` is the top predicted bird.

Design / offline-first
-----------------------
The heavy dependency (``torch``) and the model weights are both lazy:
``is_available`` is ``False`` until a TorchScript checkpoint *and* a labels file
are present on disk *and* torch + Pillow import. The detector registry skips any
detector whose ``is_available`` is ``False``, so:

- in CI (no weights, torch not installed) this detector is simply skipped;
- on a field gateway it activates automatically once the operator drops the
  model files into ``models/`` (or sets ``CLAWCAM_MODELS_DIR``).

Supplying a model
-----------------
Place two files (see ``models/README.md``):

- ``bird_classifier.torchscript.pt`` — a TorchScript image classifier that takes
  a normalised ``[1, 3, 224, 224]`` tensor (ImageNet mean/std) and returns class
  logits ``[1, N]``.
- ``bird_classifier_labels.txt`` — ``N`` species names, one per line, in class
  index order.

Any model matching that contract (a fine-tuned timm/torchvision head, a NABirds
or iNaturalist-trained classifier, etc.) drops in without code changes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from clawcam_gateway.inference.detector import BaseDetector, Detection, InferenceResult

logger = logging.getLogger(__name__)

DEFAULT_MODELS_DIR = Path(os.getenv("CLAWCAM_MODELS_DIR", "models"))
DEFAULT_WEIGHTS_NAME = "bird_classifier.torchscript.pt"
DEFAULT_LABELS_NAME = "bird_classifier_labels.txt"

# ImageNet normalisation — the standard transform the supplied TorchScript model
# is expected to have been trained against.
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)
_INPUT_SIZE = 224


class BirdClassifierDetector(BaseDetector):
    """Species classifier that emits an ``animal`` detection with a bird species."""

    def __init__(
        self,
        weights_path: str | Path | None = None,
        labels_path: str | Path | None = None,
        min_confidence: float = 0.30,
    ):
        self._weights_path = Path(weights_path) if weights_path else DEFAULT_MODELS_DIR / DEFAULT_WEIGHTS_NAME
        self._labels_path = Path(labels_path) if labels_path else DEFAULT_MODELS_DIR / DEFAULT_LABELS_NAME
        self._min_confidence = min_confidence
        self._model = None
        self._labels: list[str] | None = None

    @property
    def model_name(self) -> str:
        return "bird_classifier"

    @property
    def model_version(self) -> str:
        return "0.1.0"

    @property
    def is_available(self) -> bool:
        """True only when both weights+labels exist and torch/Pillow import."""
        if not (self._weights_path.exists() and self._labels_path.exists()):
            return False
        try:
            import torch  # noqa: F401
            from PIL import Image  # noqa: F401
        except Exception:  # noqa: BLE001 - any import problem => unavailable
            return False
        return True

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch

        self._model = torch.jit.load(str(self._weights_path), map_location="cpu").eval()
        self._labels = [
            line.strip()
            for line in self._labels_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def detect(self, image_path: Path) -> InferenceResult:
        # Defensive: the orchestrator only calls available detectors, but never raise.
        if not self.is_available:
            return InferenceResult(self.model_name, self.model_version, [])

        import torch
        from PIL import Image

        self._load()
        assert self._model is not None and self._labels is not None

        img = Image.open(image_path).convert("RGB").resize((_INPUT_SIZE, _INPUT_SIZE))
        # HWC uint8 -> CHW float tensor in [0,1], then ImageNet-normalise.
        tensor = (
            torch.tensor(list(img.getdata()), dtype=torch.float32)
            .reshape(_INPUT_SIZE, _INPUT_SIZE, 3)
            .permute(2, 0, 1)
            / 255.0
        )
        mean = torch.tensor(_IMAGENET_MEAN).view(3, 1, 1)
        std = torch.tensor(_IMAGENET_STD).view(3, 1, 1)
        batch = ((tensor - mean) / std).unsqueeze(0)

        with torch.no_grad():
            logits = self._model(batch)
            probs = torch.softmax(logits, dim=1)[0]
            confidence, index = torch.topk(probs, 1)

        conf = float(confidence[0])
        species = self._labels[int(index[0])] if int(index[0]) < len(self._labels) else None
        # Always an "animal" (this is a refinement step); species attached only
        # when the classifier is confident enough, otherwise left unknown.
        detection = Detection(
            label="animal",
            confidence=conf,
            bbox=[0.0, 0.0, 1.0, 1.0],
            species=species if conf >= self._min_confidence else None,
        )
        return InferenceResult(self.model_name, self.model_version, [detection])
