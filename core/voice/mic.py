"""Microphone capture (spec §8: STT is local for privacy).

sounddevice/numpy are imported lazily so the voice package loads without audio
deps. openWakeWord and faster-whisper both expect 16 kHz mono 16-bit PCM.

macOS TCC: the first mic access triggers a system permission prompt for the
host terminal app. request_mic_permission() forces that prompt deliberately
during setup (§8 permission walkthrough), so the grant isn't a surprise later.
"""

SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_SAMPLES = 1280  # 80 ms at 16 kHz — openWakeWord's expected chunk

# Selected input device (sounddevice index). None = auto-pick a built-in mic.
_INPUT_DEVICE: int | None = None

# Software gain applied to captured audio. Compensates for low input gain (e.g.
# when a Bluetooth headset ducks the built-in mic). Clipped to int16 range.
_INPUT_GAIN: float = 1.0


def set_input_gain(gain: float) -> None:
    global _INPUT_GAIN
    _INPUT_GAIN = max(1.0, gain)


def _apply_gain(audio):
    if _INPUT_GAIN == 1.0:
        return audio
    import numpy as np
    boosted = audio.astype(np.float32) * _INPUT_GAIN
    return np.clip(boosted, -32768, 32767).astype(np.int16)

# Bluetooth headsets expose a mic but only in hands-free (HFP) mode, which on
# macOS often captures near-silence — prefer a wired/built-in mic over these.
_BLUETOOTH_HINTS = ("airpods", "buds", "headset", "bluetooth", "wireless", "neo")
_BUILTIN_HINTS = ("macbook", "built-in", "imac", "studio display", "internal")


def _sd():
    import sounddevice  # lazy: heavy + needs PortAudio
    return sounddevice


def list_input_devices() -> list[tuple[int, str]]:
    sd = _sd()
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0]


def pick_builtin_mic() -> int | None:
    """Pick a sensible input device: a built-in mic if present, else the first
    non-Bluetooth input, else the system default."""
    devices = list_input_devices()
    for idx, name in devices:
        if any(h in name.lower() for h in _BUILTIN_HINTS):
            return idx
    for idx, name in devices:
        if not any(h in name.lower() for h in _BLUETOOTH_HINTS):
            return idx
    return devices[0][0] if devices else None


def set_input_device(index: int | None) -> None:
    global _INPUT_DEVICE
    _INPUT_DEVICE = index


def _device() -> int | None:
    return _INPUT_DEVICE if _INPUT_DEVICE is not None else pick_builtin_mic()


def record_seconds(seconds: float):
    """Record mono 16 kHz int16 audio, returning a numpy array."""
    import numpy as np
    sd = _sd()
    frames = int(seconds * SAMPLE_RATE)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
                   device=_device())
    sd.wait()
    return _apply_gain(np.squeeze(audio))


def record_until_silence(max_seconds: float = 15.0, silence_ms: float = 900,
                         start_timeout_s: float = 6.0, silence_gate: float = 0.02):
    """Record until the speaker stops (a run of trailing silence), instead of a
    fixed window. Waits up to start_timeout_s for speech to begin, then ends
    after silence_ms of quiet; hard-capped at max_seconds. Returns int16 audio."""
    import time

    import numpy as np
    frame_dur = FRAME_SAMPLES / SAMPLE_RATE  # 80 ms
    frames: list = []
    started = False
    silent_run = 0.0
    start = time.time()
    gen = frame_stream()
    try:
        for frame in gen:
            frames.append(frame)
            amp = float(np.abs(frame.astype(np.float32) / 32768.0).max())
            elapsed = time.time() - start
            if amp >= silence_gate:
                started = True
                silent_run = 0.0
            else:
                silent_run += frame_dur
            if started and silent_run >= silence_ms / 1000:
                break
            if not started and elapsed >= start_timeout_s:
                break
            if elapsed >= max_seconds:
                break
    finally:
        gen.close()  # closes the InputStream promptly
    if not frames:
        return np.zeros(0, dtype="int16")
    return np.concatenate(frames)


def frame_stream(stop_event=None):
    """Yield successive int16 frames from the mic for wake-word streaming.
    stop_event: optional threading.Event to end the stream.

    Uses a callback-fed queue rather than InputStream.read(): the pull-read path
    underflows to silence on macOS (observed max_amp≈0.0002 vs 0.999), so the
    callback (push) model is the reliable streaming idiom here.
    """
    import queue

    import numpy as np
    sd = _sd()
    frames: queue.Queue = queue.Queue()

    def _callback(indata, frame_count, time_info, status):
        frames.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
                        blocksize=FRAME_SAMPLES, callback=_callback, device=_device()):
        while stop_event is None or not stop_event.is_set():
            try:
                data = frames.get(timeout=1.0)
            except queue.Empty:
                continue
            yield _apply_gain(np.squeeze(data))


def request_mic_permission() -> bool:
    """Force the macOS mic TCC prompt by opening a short input stream.
    Returns True if capture succeeded (permission granted)."""
    try:
        sd = _sd()
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16"):
            pass
        return True
    except Exception:
        return False
