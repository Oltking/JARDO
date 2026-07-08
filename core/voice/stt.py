"""Speech-to-text via faster-whisper (spec §8: local, for privacy).

Source: docs/vendor/voice/faster-whisper-readme.md
  from faster_whisper import WhisperModel
  model = WhisperModel(size, device="cpu", compute_type="int8")
  segments, info = model.transcribe(audio, beam_size=5, vad_filter=True)

Default model "small.en": markedly more accurate than "base" on real speech,
still fast on Apple Silicon CPU. Lazy-loaded and cached. vad_filter drops
non-speech audio (built-in Silero VAD), which is the main cure for whisper
hallucinating "nonsense" on quiet/short clips.
"""

DEFAULT_MODEL = "small.en"

# Priming vocabulary (faster-whisper `initial_prompt`): biases recognition toward
# the words Jardo actually cares about, so accented/non-native English lands on
# the right term ("super vice" -> "supervise") instead of a phonetic guess. This
# is the cheapest, biggest win for non-native speakers — it runs locally.
_VOCAB_PROMPT = (
    "Jardo, supervise, Claude, Gemini, Codex, Cursor, terminal, commit, push, "
    "pull request, branch, pytest, npm, pnpm, build, deploy, resume, project, "
    "repository, permission, approve, decline, yes, no, stop, where am I, "
    "what am I working on, keep going, start a new project."
)


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

    def warmup(self) -> None:
        """Load the model + run a tiny transcription so the FIRST real one isn't
        paying the model-load cost (which is what makes the first reply feel slow)."""
        import numpy as np
        try:
            self.transcribe(np.zeros(1600, dtype="int16"))
        except Exception:  # noqa: BLE001 — warmup is best-effort
            pass

    def transcribe(self, audio) -> str:
        """audio: path to a file OR a numpy float32/int16 array at 16 kHz."""
        import numpy as np

        from core.config import settings
        model = self._ensure_model()
        # Optional noise suppression (config flag; transparent no-op if the extra
        # isn't installed). Runs on int16 before the float conversion below.
        if hasattr(audio, "dtype") and audio.dtype == np.int16:
            if settings.voice_denoise:
                from core.voice.denoise import denoise
                audio = denoise(audio)
        if hasattr(audio, "dtype") and audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0  # whisper wants float32 in [-1,1]
        segments, _info = model.transcribe(
            audio, beam_size=settings.voice_stt_beam_size, language=self._language,
            condition_on_previous_text=False,  # reduce hallucination
            initial_prompt=_VOCAB_PROMPT,       # bias toward Jardo's vocabulary
            # Silero VAD: skip non-speech so silence isn't transcribed as garbage.
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
