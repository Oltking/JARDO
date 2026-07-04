"""Voice loop orchestration with injected fakes — no audio hardware or models."""

from core.voice.loop import VoiceConfig, VoiceLoop
from core.voice.tts import MacSayTTS, get_tts


class _FakeSTT:
    def __init__(self, text):
        self._text = text

    def transcribe(self, audio):
        return self._text


class _FakeTTS:
    def __init__(self):
        self.said = []

    def speak(self, text):
        self.said.append(text)


def test_listen_once_transcribes_and_responds():
    tts = _FakeTTS()
    loop = VoiceLoop(
        wake_detector=None, stt=_FakeSTT("what is the weather"), tts=tts,
        chat_fn=lambda text: f"reply to: {text}",
        record_fn=lambda seconds: b"fake-audio",
        config=VoiceConfig(),
    )
    reply = loop.listen_once()
    assert reply == "reply to: what is the weather"
    assert tts.said == ["reply to: what is the weather"]


def test_listen_once_ignores_empty_transcription():
    tts = _FakeTTS()
    called = {"chat": False}

    def chat_fn(text):
        called["chat"] = True
        return "x"

    loop = VoiceLoop(
        wake_detector=None, stt=_FakeSTT("   "), tts=tts, chat_fn=chat_fn,
        record_fn=lambda s: b"", config=VoiceConfig(),
    )
    assert loop.listen_once() == ""
    assert called["chat"] is False  # no empty utterance sent to the model


def test_run_triggers_listen_once_on_wake():
    tts = _FakeTTS()

    class _Wake:
        def listen(self, timeout_seconds):
            return True

    loop = VoiceLoop(
        wake_detector=_Wake(), stt=_FakeSTT("what time is it"), tts=tts,
        chat_fn=lambda text: f"answer: {text}",
        record_fn=lambda s: b"audio", config=VoiceConfig(),
    )
    loop.run(max_wakes=1)
    # "Yes?" acknowledgement + the chat answer were spoken
    assert "answer: what time is it" in tts.said


def test_get_tts_defaults_to_macos_say():
    # `say` exists on the macOS build host; get_tts returns the say backend.
    tts = get_tts("say")
    assert isinstance(tts, MacSayTTS)


def test_get_tts_piper_falls_back_when_unavailable():
    # No piper binary/model → falls back to say rather than raising.
    tts = get_tts("piper", model_path="/nonexistent/voice.onnx")
    assert isinstance(tts, MacSayTTS)
