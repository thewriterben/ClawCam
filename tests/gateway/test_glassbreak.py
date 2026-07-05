"""Tests for the YAMNet glass-break / alarm audio classifier scaffold.

tensorflow isn't installed in CI, so these cover the label map, availability
gating, the composite classifier, and the default-classifier fallback. The
YAMNet inference path activates only with the [audio] extra installed and is
exercised in the field test.
"""

from __future__ import annotations

from clawcam_gateway.audio.classifier import (
    AudioClassification,
    BaseAudioClassifier,
    CompositeAudioClassifier,
    MockAudioClassifier,
    get_default_classifier,
)
from clawcam_gateway.audio.glassbreak import GlassBreakClassifier, map_audio_event


def test_metadata():
    c = GlassBreakClassifier()
    assert c.name == "yamnet_alarm"
    assert c.version == "0.1.0"


def test_label_map():
    assert map_audio_event("Glass") == "glass_break"
    assert map_audio_event("Shatter") == "glass_break"
    assert map_audio_event("Siren") == "alarm"
    assert map_audio_event("Screaming") == "scream"
    assert map_audio_event("Gunshot, gunfire") == "gunshot"
    assert map_audio_event("Bird") is None        # not security-relevant
    assert map_audio_event("Speech") is None


def test_unavailable_without_tensorflow():
    assert GlassBreakClassifier().is_available is False


def test_classify_safe_when_unavailable(tmp_path):
    c = GlassBreakClassifier()
    assert c.classify(tmp_path / "clip.wav") == []


def test_default_classifier_is_mock_when_allowed(monkeypatch):
    # No real audio models installed in CI -> deterministic mock, but only
    # when mocks are explicitly allowed (they fabricate classifications).
    monkeypatch.setenv("CLAWCAM_ALLOW_MOCKS", "true")
    assert isinstance(get_default_classifier(), MockAudioClassifier)


def test_default_classifier_unavailable_without_mock_optin(monkeypatch):
    monkeypatch.delenv("CLAWCAM_ALLOW_MOCKS", raising=False)
    c = get_default_classifier()
    assert not isinstance(c, MockAudioClassifier)
    assert c.is_available is False


# ── CompositeAudioClassifier ─────────────────────────────────────────────────

class _Unavailable(BaseAudioClassifier):
    name, version = "unavail", "0"

    @property
    def is_available(self) -> bool:
        return False

    def classify(self, audio_path):
        raise AssertionError("should not be called when unavailable")


class _Boom(BaseAudioClassifier):
    name, version = "boom", "0"

    @property
    def is_available(self) -> bool:
        return True

    def classify(self, audio_path):
        raise RuntimeError("kaboom")


def test_composite_available_if_any():
    assert CompositeAudioClassifier([_Unavailable()]).is_available is False
    assert CompositeAudioClassifier([_Unavailable(), MockAudioClassifier()]).is_available is True


def test_composite_concatenates_and_skips_unavailable(tmp_path):
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"audio-bytes")
    comp = CompositeAudioClassifier([
        MockAudioClassifier(empty_probability=0.0),
        _Unavailable(),
        MockAudioClassifier(empty_probability=0.0),
    ])
    hits = comp.classify(clip)
    # Two available mocks, each emits one hit; the unavailable one is skipped.
    assert len(hits) == 2
    assert all(isinstance(h, AudioClassification) for h in hits)


def test_composite_swallows_subclassifier_errors(tmp_path):
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"x")
    comp = CompositeAudioClassifier([_Boom(), MockAudioClassifier(empty_probability=0.0)])
    # _Boom raises but must not abort; the mock's hit still comes through.
    assert len(comp.classify(clip)) == 1
