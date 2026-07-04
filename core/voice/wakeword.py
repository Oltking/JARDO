"""Wake-word detection via openWakeWord (spec §8: wake word "JARVIS").

Source: docs/vendor/voice/openwakeword-readme.md
  from openwakeword.model import Model
  model = Model(wakeword_models=["hey jarvis"])   # ships a pretrained hey_jarvis
  prediction = model.predict(frame)               # frame: 16-bit 16 kHz PCM
  default positive threshold 0.5

openWakeWord ships a pretrained "hey jarvis" model — no custom training needed
for the MVP. Custom "JARVIS"-only training is a later refinement (§4.7).
"""

DEFAULT_WAKEWORD = "hey jarvis"
DEFAULT_THRESHOLD = 0.5


class WakeWordDetector:
    def __init__(self, wakeword: str = DEFAULT_WAKEWORD, threshold: float = DEFAULT_THRESHOLD,
                 vad_threshold: float = 0.5):
        self._wakeword = wakeword
        self._threshold = threshold
        self._vad_threshold = vad_threshold
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from openwakeword.model import Model  # lazy
            try:
                import openwakeword
                openwakeword.utils.download_models()  # one-time pretrained model fetch
            except Exception:
                pass
            self._model = Model(wakeword_models=[self._wakeword],
                                vad_threshold=self._vad_threshold)
        return self._model

    def score(self, frame) -> float:
        model = self._ensure_model()
        prediction = model.predict(frame)
        # prediction keys are model names (e.g. "hey_jarvis"); take the max score.
        return max(prediction.values()) if prediction else 0.0

    def detected(self, frame) -> bool:
        return self.score(frame) >= self._threshold
