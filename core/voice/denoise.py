"""Optional neural noise suppression before STT (spec §8).

Off by default (JARDO_VOICE_DENOISE=true to enable). Uses DeepFilterNet — a
free, permissively-licensed, on-device model (no cloud, no per-seat cost, fits
the privacy-first design). It runs at 48 kHz, so we resample our 16 kHz mic audio
up, enhance, and resample back.

Deliberately measured, not assumed: Whisper is trained on noisy audio and can do
*worse* on aggressively denoised input, so this is a flag we A/B, not a default.
If DeepFilterNet (an optional extra) isn't installed, denoise() is a transparent
no-op — the pipeline keeps working exactly as before.
"""

MIC_SR = 16_000

_MODEL = None          # (model, df_state) cached after first load
_UNAVAILABLE = False   # set once if the deps aren't importable, to stop retrying


def available() -> bool:
    try:
        import df  # noqa: F401  (deepfilternet)
        return True
    except Exception:  # noqa: BLE001
        return False


def _load():
    global _MODEL, _UNAVAILABLE
    if _MODEL is not None or _UNAVAILABLE:
        return _MODEL
    try:
        from df.enhance import init_df
        model, state, _ = init_df()
        _MODEL = (model, state)
    except Exception:  # noqa: BLE001 — missing dep / load failure → permanent no-op
        _UNAVAILABLE = True
        _MODEL = None
    return _MODEL


def denoise(audio_int16):
    """Suppress background noise in mono 16 kHz int16 audio; returns the same
    shape/dtype. Transparent no-op if DeepFilterNet isn't available or the clip
    is empty."""
    import numpy as np

    if audio_int16 is None or getattr(audio_int16, "size", 0) == 0:
        return audio_int16
    loaded = _load()
    if loaded is None:
        return audio_int16  # graceful: unchanged
    model, state = loaded
    try:
        import torch
        from df.enhance import enhance
        from scipy.signal import resample_poly

        sr = int(state.sr())  # DeepFilterNet's native rate (48 kHz)
        x = audio_int16.astype(np.float32) / 32768.0
        up = resample_poly(x, sr, MIC_SR) if sr != MIC_SR else x
        out = enhance(model, state, torch.from_numpy(up).unsqueeze(0))
        out = out.squeeze(0).cpu().numpy()
        down = resample_poly(out, MIC_SR, sr) if sr != MIC_SR else out
        return np.clip(down * 32768.0, -32768, 32767).astype(np.int16)
    except Exception:  # noqa: BLE001 — never let denoise break capture
        return audio_int16
