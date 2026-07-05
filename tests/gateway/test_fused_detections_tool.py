"""Tool-level test for get_fused_detections — stub DB, no real database needed."""

from clawcam_gateway.tools.clawcam_tools import get_fused_detections


class _StubDB:
    def __init__(self, rows):
        self._rows = rows

    def list_inference_results_for_event(self, event_id):
        return list(self._rows)


class _Ctx:
    def __init__(self, rows):
        self.db = _StubDB(rows)


def test_fuses_chain_rows_for_event():
    rows = [
        {"model_name": "megadetector_v5",
         "detections": [{"label": "animal", "confidence": 0.92, "bbox": [0, 0, 0.5, 0.5], "species": None}]},
        {"model_name": "bird_classifier",
         "detections": [{"label": "bird", "confidence": 0.80, "bbox": [0.01, 0.0, 0.5, 0.5],
                         "species": "American robin"}]},
    ]
    out = get_fused_detections(_Ctx(rows), "evt-1", iou_threshold=0.5)
    assert out["ok"] is True
    assert out["event_id"] == "evt-1"
    assert out["stored"] is False  # read-time fallback (no stored fused row)
    assert out["detectors"] == ["megadetector_v5", "bird_classifier"]
    fused = out["fused"]
    assert len(fused["detections"]) == 1
    assert fused["top_label"] == "bird"
    assert fused["top_species"] == "American robin"


def test_stored_fused_row_is_returned_directly():
    rows = [
        {"model_name": "megadetector_v5", "role": "chain_member",
         "detections": [{"label": "animal", "confidence": 0.92, "bbox": [0, 0, 0.5, 0.5], "species": None}]},
        {"model_name": "bird_classifier", "role": "chain_member",
         "detections": [{"label": "bird", "confidence": 0.80, "bbox": [0.01, 0.0, 0.5, 0.5],
                         "species": "American robin"}]},
        {"model_name": "fused", "role": "fused",
         "top_label": "bird", "top_confidence": 0.92, "top_species": "American robin",
         "detections": [{"label": "bird", "confidence": 0.92, "bbox": [0, 0, 0.5, 0.5],
                         "species": "American robin"}]},
    ]
    out = get_fused_detections(_Ctx(rows), "evt-2")
    assert out["ok"] is True
    assert out["stored"] is True
    # Detectors list names only the member rows, not the fused row itself.
    assert out["detectors"] == ["megadetector_v5", "bird_classifier"]
    fused = out["fused"]
    assert len(fused["detections"]) == 1
    assert fused["top_label"] == "bird"
    assert fused["top_species"] == "American robin"


def test_missing_event_is_reported():
    out = get_fused_detections(_Ctx([]), "nope")
    assert out["ok"] is False
    assert "no inference results" in out["error"]
