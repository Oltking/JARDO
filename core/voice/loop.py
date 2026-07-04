"""Voice loop (spec §8): wake word → STT → intent → TTS reply.

Wake ("hey jarvis") → capture a short utterance → transcribe locally → send to
the core /chat endpoint (same routing/memory as text chat) → speak the reply.
Tap-to-talk is the alternative entry (listen_once) when wake-word is off.

All heavy pieces are injected or lazily built so this orchestration is testable
with fakes. The real wiring is assembled in build_voice_loop().
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger("jarvis.voice")


@dataclass
class VoiceConfig:
    utterance_seconds: float = 5.0
    wake_enabled: bool = True


class VoiceLoop:
    def __init__(self, detector, stt, tts, chat_fn: Callable[[str], str],
                 record_fn: Callable[[float], object], frame_source: Callable[[], object],
                 config: VoiceConfig | None = None):
        self._detector = detector
        self._stt = stt
        self._tts = tts
        self._chat_fn = chat_fn            # (text) -> reply text (calls core /chat)
        self._record_fn = record_fn        # (seconds) -> audio array
        self._frame_source = frame_source  # () -> iterable of frames
        self._config = config or VoiceConfig()

    def listen_once(self) -> str:
        """Tap-to-talk: record one utterance, transcribe, respond, speak."""
        audio = self._record_fn(self._config.utterance_seconds)
        text = self._stt.transcribe(audio)
        if not text.strip():
            return ""
        reply = self._chat_fn(text)
        self._tts.speak(reply)
        return reply

    def run(self, max_wakes: int | None = None) -> None:  # pragma: no cover (hardware loop)
        """Blocking wake-word loop. max_wakes bounds it for testing/demo."""
        self._tts.speak("Voice loop ready. Say, hey JARVIS, to begin.")
        wakes = 0
        for frame in self._frame_source():
            if self._detector.detected(frame):
                logger.info("wake word detected")
                self._tts.speak("Yes?")
                self.listen_once()
                wakes += 1
                if max_wakes is not None and wakes >= max_wakes:
                    return
