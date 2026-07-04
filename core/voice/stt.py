"""Speech-to-text via faster-whisper (spec §8: local, for privacy).

Source: docs/vendor/voice/faster-whisper-readme.md
  from faster_whisper import WhisperModel
  model = WhisperModel(size, device="cpu", compute_type="int8")
  segments, info = model.transcribe(audio, beam_size=5)   # segments is a generator

Model default "base" (~140 MB, good accuracy on Apple Silicon CPU). Lazy-loaded
and cached so the first transcription pays the load cost, not import.
"""

DEFAULT_MODEL = "base"


class SpeechToText:
    def __init__(self, model_size: str = DEFAULT_MODEL, compute_type: str = "int8",
                 language: str = "en"):
        self._model_size = model_size
        self._compute_type = compute_type
        # Pin the language: whisper's auto-detect hallucinates on quiet/short
        # clips (observed: silence transcribed as Russian). Set None to auto-detect.
        self._language = language
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # lazy: heavy import + model load
            self._model = WhisperModel(self._model_size, device="cpu",
                                       compute_type=self._compute_type)
        return self._model

    def transcribe(self, audio) -> str:
        """audio: path to a file OR a numpy float32/int16 array at 16 kHz."""
        import numpy as np
        model = self._ensure_model()
        if hasattr(audio, "dtype") and audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0  # whisper wants float32 in [-1,1]
        segments, _info = model.transcribe(
            audio, beam_size=5, language=self._language,
            condition_on_previous_text=False,  # further reduces hallucination
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
