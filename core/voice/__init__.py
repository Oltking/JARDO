"""Voice + presence subsystem (spec §8).

Voice is fully optional (§8). Heavy deps (faster-whisper, openwakeword,
sounddevice) are imported lazily inside the modules that need them, so this
package — and the presence-ritual logic in particular — imports and tests
without any audio hardware or ML models present.
"""
