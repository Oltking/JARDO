"""Wake-word detection via openWakeWord (spec §8: wake word "Jardo").

Source: docs/vendor/voice/openwakeword-readme.md (documents an older API; the
installed openwakeword==0.4.0 differs — verified live 2026-07-04):
  import openwakeword
  from openwakeword.model import Model
  paths = openwakeword.get_pretrained_model_paths()   # ships hey_jarvis_v0.1.onnx
  model = Model(wakeword_model_paths=[hey_jarvis_path])
  prediction = model.predict(frame)   # frame: int16 16 kHz PCM, 1280 samples
  # → {"hey_jarvis_v0.1": score in [0,1]}; default positive threshold 0.5

The pretrained "hey jarvis" model ships bundled with the pip package — no
download needed (its filename is the openWakeWord model id, unrelated to the
Jardo brand). Custom "Jardo"-only wake training is a later refinement (§4.7).
"""

DEFAULT_THRESHOLD = 0.5
_WAKEWORD_KEY = "jarvis"


def _hey_jarvis_path() -> str:
    import openwakeword
    for path in openwakeword.get_pretrained_model_paths():
        if _WAKEWORD_KEY in path.lower():
            return path
    raise RuntimeError("bundled hey_jarvis model not found in openwakeword")


class WakeWordDetector:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD,
                 vad_threshold: float = 0.0):
        self._threshold = threshold
        self._vad_threshold = vad_threshold
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from openwakeword.model import Model  # lazy: heavy onnxruntime import
            kwargs = {"wakeword_model_paths": [_hey_jarvis_path()]}
            if self._vad_threshold:
                kwargs["vad_threshold"] = self._vad_threshold
            self._model = Model(**kwargs)
        return self._model

    def score(self, frame) -> float:
        prediction = self._ensure_model().predict(frame)
        return max(prediction.values()) if prediction else 0.0

    def detected(self, frame) -> bool:
        return self.score(frame) >= self._threshold


# openWakeWord 0.4.0 does not score under onnxruntime 1.27 in this env (see
# [[jardo-wakeword-todo]]). WhisperWakeDetector is the reliable default: it
# reuses the proven STT path — capture short windows, skip silence, transcribe,
# and trigger when the wake word appears. Heavier on CPU than a dedicated wake
# model, fine for a single-user MVP.
# Brand wake word is "Jardo" (BRANDING.md). whisper mishears it various ways;
# match generously. "hey jarvis"/"javis" kept as transitional aliases.
_WAKE_PHRASES = ("jardo", "hey jardo", "jardu", "jarda", "jar do", "hey jarvis", "javis")
_SILENCE_GATE = 0.02  # skip transcribing windows quieter than this


class WhisperWakeDetector:
    def __init__(self, stt, phrases: tuple[str, ...] = _WAKE_PHRASES,
                 window_seconds: float = 2.0, silence_gate: float = _SILENCE_GATE):
        self._stt = stt
        self._phrases = tuple(p.lower() for p in phrases)
        self._window = window_seconds
        self._silence_gate = silence_gate

    def _matches(self, transcript: str) -> bool:
        t = transcript.lower()
        return any(p in t for p in self._phrases)

    def listen(self, timeout_seconds: float = 30.0) -> bool:
        """Block until the wake word is heard or timeout. Returns True on wake."""
        import time

        import numpy as np
        from core.voice import mic

        start = time.time()
        while time.time() - start < timeout_seconds:
            audio = mic.record_seconds(self._window)
            amp = float(np.abs(audio.astype(np.float32) / 32768.0).max())
            if amp < self._silence_gate:
                continue  # silence — don't waste a transcription
            if self._matches(self._stt.transcribe(audio)):
                return True
        return False
