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
        # Serialize model init so the background warmup and a live transcribe call
        # can't both instantiate/download the model at once (a crash-prone race).
        import threading
        self._load_lock = threading.Lock()

    def _bundled_dir(self) -> str | None:
        """A model shipped inside a frozen (offline) build, if present."""
        import os
        bundle = os.environ.get("JARDO_BUNDLE_DIR")
        if bundle:
            cand = os.path.join(bundle, "models", "whisper", self._model_size)
            if os.path.isfile(os.path.join(cand, "model.bin")):
                return cand
        return None

    def _repo_id(self) -> str:
        return f"Systran/faster-whisper-{self._model_size}"

    def is_ready(self) -> bool:
        """True if the model can load without a network download: already loaded,
        bundled in the app, or present in the standard Hugging Face cache (which is
        where faster-whisper keeps it — including copies from before this build)."""
        if self._model is not None or self._bundled_dir() is not None:
            return True
        try:
            from huggingface_hub import try_to_load_from_cache
            hit = try_to_load_from_cache(self._repo_id(), "model.bin")
            return isinstance(hit, str)
        except Exception:  # noqa: BLE001 — if we can't tell, assume not cached
            return False

    def _ensure_model(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:  # re-check inside the lock
                    from faster_whisper import WhisperModel  # lazy: heavy load
                    # Prefer a bundled copy; otherwise let faster-whisper use its
                    # DEFAULT cache (~/.cache/huggingface or $HF_HOME) so an
                    # already-downloaded model is reused and a fresh one is fetched
                    # once (~180 MB) to the standard location.
                    source = self._bundled_dir() or self._model_size
                    self._model = WhisperModel(source, device="cpu",
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
