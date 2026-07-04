"""WhisperWakeDetector — the STT-based wake detector (openWakeWord is non-
functional in this env; see jarvis-wakeword-todo). Phrase matching is pure
logic; the listen() loop is exercised with a fake mic via monkeypatch."""

import numpy as np
import pytest

from core.voice.wakeword import WhisperWakeDetector


class _FakeSTT:
    def __init__(self, transcript):
        self.transcript = transcript

    def transcribe(self, audio):
        return self.transcript


def test_matches_wake_phrases():
    det = WhisperWakeDetector(_FakeSTT(""))
    assert det._matches("hey jarvis, what's up")
    assert det._matches("JARVIS")
    assert det._matches("ok javis")  # whisper mishears jarvis as javis
    assert not det._matches("hello there computer")


def test_listen_triggers_on_wake_word(monkeypatch):
    from core.voice import mic
    # loud, non-silent audio so the silence gate passes
    loud = (np.ones(40000) * 8000).astype(np.int16)
    monkeypatch.setattr(mic, "record_seconds", lambda s: loud)

    det = WhisperWakeDetector(_FakeSTT("hey jarvis"), window_seconds=0.1)
    assert det.listen(timeout_seconds=5) is True


def test_listen_skips_silence_without_transcribing(monkeypatch):
    from core.voice import mic
    silent = np.zeros(40000, dtype=np.int16)
    monkeypatch.setattr(mic, "record_seconds", lambda s: silent)

    calls = {"n": 0}

    class _CountingSTT:
        def transcribe(self, audio):
            calls["n"] += 1
            return "jarvis"

    det = WhisperWakeDetector(_CountingSTT(), window_seconds=0.05)
    # all windows are silent → gated out → never transcribed → times out
    assert det.listen(timeout_seconds=0.3) is False
    assert calls["n"] == 0


def test_listen_times_out_when_no_wake(monkeypatch):
    from core.voice import mic
    loud = (np.ones(40000) * 8000).astype(np.int16)
    monkeypatch.setattr(mic, "record_seconds", lambda s: loud)

    det = WhisperWakeDetector(_FakeSTT("just some chatter"), window_seconds=0.05)
    assert det.listen(timeout_seconds=0.3) is False
