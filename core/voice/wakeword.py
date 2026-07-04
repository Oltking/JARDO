"""Wake-word detection via openWakeWord (spec §8: wake word "JARVIS").

Source: docs/vendor/voice/openwakeword-readme.md (documents an older API; the
installed openwakeword==0.4.0 differs — verified live 2026-07-04):
  import openwakeword
  from openwakeword.model import Model
  paths = openwakeword.get_pretrained_model_paths()   # ships hey_jarvis_v0.1.onnx
  model = Model(wakeword_model_paths=[hey_jarvis_path])
  prediction = model.predict(frame)   # frame: int16 16 kHz PCM, 1280 samples
  # → {"hey_jarvis_v0.1": score in [0,1]}; default positive threshold 0.5

The pretrained "hey jarvis" model ships bundled with the pip package — no
download needed. Custom "JARVIS"-only training is a later refinement (§4.7).
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
