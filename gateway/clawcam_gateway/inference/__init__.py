"""ClawCam inference pipeline — species detection on captured images."""
from .boxops import iou, merge_results, nms
from .detector import BaseDetector, Detection, InferenceResult, MockDetector
from .pipeline import InferencePipeline

__all__ = [
    "BaseDetector",
    "Detection",
    "InferenceResult",
    "InferencePipeline",
    "MockDetector",
    "iou",
    "merge_results",
    "nms",
]
