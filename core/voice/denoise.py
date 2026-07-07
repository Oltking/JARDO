"""Optional noise suppression before STT (spec §8).

Off by default (JARDO_VOICE_DENOISE=true to enable). Uses noisereduce — a free,
MIT-licensed, on-device spectral-gating denoiser: pure numpy/scipy (no torch),
numpy-2 compatible, and works natively at our 16 kHz mic rate. We chose it over
DeepFilterNet because DFN pins numpy<2 and conflicts with the voice stack.

Measured, not assumed: Whisper is trained on noisy audio and can do *worse* on
over-denoised input, so this is a flag we A/B (jardo denoise-test), not a
default. If noisereduce (an optional extra) isn't installed, denoise() is a
transparent no-op — the pipeline keeps working exactly as before.
"""

MIC_SR = 16_000
_UNAVAILABLE = False  # set once if the dep isn't importable, to stop retrying


def available() -> bool:
    try:
        import noisereduce  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def denoise(audio_int16):
    """Suppress background noise in mono 16 kHz int16 audio; returns the same
    shape/dtype. Transparent no-op if noisereduce isn't available or the clip is
    empty — it can never break capture."""
    import numpy as np

    if audio_int16 is None or getattr(audio_int16, "size", 0) == 0:
        return audio_int16
    global _UNAVAILABLE
    if _UNAVAILABLE:
        return audio_int16
    try:
        import noisereduce as nr

        x = audio_int16.astype(np.float32) / 32768.0
        # Non-stationary: estimate the noise profile adaptively across the clip,
        # so it handles changing background noise without a separate noise sample.
        reduced = nr.reduce_noise(y=x, sr=MIC_SR, stationary=False)
        return np.clip(reduced * 32768.0, -32768, 32767).astype(np.int16)
    except ImportError:
        _UNAVAILABLE = True
        return audio_int16
    except Exception:  # noqa: BLE001 — never let denoise break capture
        return audio_int16
