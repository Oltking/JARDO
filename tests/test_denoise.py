"""Noise suppression must be a transparent no-op when its optional dep is absent
or the clip is empty — it can never break capture (spec §8)."""

import numpy as np

from core.voice import denoise


def test_denoise_is_noop_without_the_dep(monkeypatch):
    # Force the "not installed" path.
    monkeypatch.setattr(denoise, "_UNAVAILABLE", True)
    audio = (np.random.default_rng(0).integers(-2000, 2000, 1600)).astype(np.int16)
    out = denoise.denoise(audio)
    assert out.dtype == np.int16
    assert np.array_equal(out, audio)  # unchanged


def test_denoise_handles_empty_and_none():
    assert denoise.denoise(None) is None
    empty = np.zeros(0, dtype=np.int16)
    assert denoise.denoise(empty).size == 0


def test_transcribe_skips_denoise_when_flag_off(monkeypatch):
    # With the flag off, transcribe must not even import/call denoise.
    from core.config import settings
    from core.voice.stt import SpeechToText

    monkeypatch.setattr(settings, "voice_denoise", False)

    def _boom(_):
        raise AssertionError("denoise called while flag is off")

    monkeypatch.setattr(denoise, "denoise", _boom)

    stt = SpeechToText()
    stt._model = type("M", (), {
        "transcribe": lambda self, *a, **k: ([], None)
    })()
    # int16 input, flag off → denoise must not be invoked.
    assert stt.transcribe(np.zeros(1600, dtype=np.int16)) == ""
