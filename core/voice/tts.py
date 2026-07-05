"""Text-to-speech (spec §8: female voice).

Two backends behind one interface:
- MacSayTTS (default): the macOS `say` command with a female system voice
  (Samantha). Zero dependencies, zero downloads, works immediately — the right
  default for a macOS-first build (§3) and for getting a voice today.
- PiperTTS (optional): Piper neural TTS for a bespoke local voice, per the spec's
  named engine. Source: docs/vendor/voice/piper-cli.md, piper-voices.md. Enabled
  by config once a voice model is downloaded; falls back to `say` if unavailable.

The spec names Piper/Kokoro; `say` is the pragmatic default so Jardo has a
voice before any model download. Swappable via settings.voice_tts_backend.
"""

import shutil
import subprocess


class TTSUnavailable(RuntimeError):
    pass


class MacSayTTS:
    def __init__(self, voice: str = "Samantha", rate_wpm: int = 174):
        if shutil.which("say") is None:
            raise TTSUnavailable("macOS `say` not found (macOS-first backend)")
        self._voice = voice
        self._rate = rate_wpm

    def speak(self, text: str) -> None:
        subprocess.run(["say", "-v", self._voice, "-r", str(self._rate), text], check=False)

    def synthesize_to_wav(self, text: str, path: str) -> str:
        # `say -o file.aiff` then convert; keep it simple with aiff which afplay reads.
        subprocess.run(["say", "-v", self._voice, "-o", path, text], check=False)
        return path


class PiperTTS:
    """Piper neural TTS via the Python API (natural prosody, local, offline).
    Requires a downloaded voice (.onnx + .onnx.json). Source: docs/vendor/voice/
    piper-api-python.md. The voice is loaded once and reused."""

    def __init__(self, model_path: str):
        from pathlib import Path
        if not Path(model_path).exists():
            raise TTSUnavailable(f"piper voice not found: {model_path}")
        from piper import PiperVoice
        self._voice = PiperVoice.load(model_path)

    def synthesize_to_wav(self, text: str, path: str) -> str:
        import wave
        with wave.open(path, "wb") as wf:
            self._voice.synthesize_wav(text, wf)
        return path

    def speak(self, text: str) -> None:
        wav = "/tmp/jardo_piper.wav"
        self.synthesize_to_wav(text, wav)
        subprocess.run(["afplay", wav], check=False)


def get_tts(backend: str = "say", *, voice: str = "Samantha", rate_wpm: int = 174,
            model_path: str | None = None):
    if backend == "piper" and model_path:
        try:
            return PiperTTS(model_path)
        except Exception:  # noqa: BLE001 — any load failure falls back to `say`
            pass
    return MacSayTTS(voice=voice, rate_wpm=rate_wpm)
