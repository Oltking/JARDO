"""Text-to-speech (spec §8: female voice).

Two backends behind one interface:
- MacSayTTS (default): the macOS `say` command with a female system voice
  (Samantha). Zero dependencies, zero downloads, works immediately — the right
  default for a macOS-first build (§3) and for getting a voice today.
- PiperTTS (optional): Piper neural TTS for a bespoke local voice, per the spec's
  named engine. Source: docs/vendor/voice/piper-cli.md, piper-voices.md. Enabled
  by config once a voice model is downloaded; falls back to `say` if unavailable.

The spec names Piper/Kokoro; `say` is the pragmatic default so JARVIS has a
voice before any model download. Swappable via settings.voice_tts_backend.
"""

import shutil
import subprocess


class TTSUnavailable(RuntimeError):
    pass


class MacSayTTS:
    def __init__(self, voice: str = "Samantha", rate_wpm: int = 180):
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
    """Piper neural TTS. Requires a downloaded voice (.onnx + .onnx.json) and the
    piper binary/package. Source: docs/vendor/voice/piper-cli.md."""

    def __init__(self, model_path: str, piper_bin: str = "piper"):
        if shutil.which(piper_bin) is None:
            raise TTSUnavailable(f"piper binary '{piper_bin}' not found")
        self._model = model_path
        self._bin = piper_bin

    def speak(self, text: str) -> None:
        wav = "/tmp/jarvis_piper.wav"
        self.synthesize_to_wav(text, wav)
        subprocess.run(["afplay", wav], check=False)

    def synthesize_to_wav(self, text: str, path: str) -> str:
        # piper reads text on stdin, writes wav to --output_file (piper-cli.md).
        subprocess.run([self._bin, "--model", self._model, "--output_file", path],
                       input=text.encode(), check=False)
        return path


def get_tts(backend: str = "say", **kwargs):
    if backend == "piper":
        try:
            return PiperTTS(**kwargs)
        except TTSUnavailable:
            pass  # fall back to say
    return MacSayTTS(**{k: v for k, v in kwargs.items() if k in ("voice", "rate_wpm")})
