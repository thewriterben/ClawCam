"""ClawCam inference pipeline — species detection on captured images."""
from .detector import BaseDetector, Detection, InferenceResult, MockDetector
from .pipeline import InferencePipeline

__all__ = [
    "BaseDetector",
    "Detection",
    "InferenceResult",
    "InferencePipeline",
    "MockDetector",
]
