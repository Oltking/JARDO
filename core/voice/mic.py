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


def _sd():
    import sounddevice  # lazy: heavy + needs PortAudio
    return sounddevice


def record_seconds(seconds: float):
    """Record mono 16 kHz int16 audio, returning a numpy array."""
    import numpy as np
    sd = _sd()
    frames = int(seconds * SAMPLE_RATE)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16")
    sd.wait()
    return np.squeeze(audio)


def frame_stream(stop_event=None):
    """Yield successive int16 frames from the mic for wake-word streaming.
    stop_event: optional threading.Event to end the stream."""
    import numpy as np
    sd = _sd()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
                        blocksize=FRAME_SAMPLES) as stream:
        while stop_event is None or not stop_event.is_set():
            data, _ = stream.read(FRAME_SAMPLES)
            yield np.squeeze(data)


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
