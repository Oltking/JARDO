"""Non-secret runtime configuration.

Secrets (API keys, key material) are NEVER configured here — they live in the
macOS Keychain via core.secrets (SECURITY.md rule 3). Everything below is safe
to appear in a process listing.
"""

import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_keys() -> set[str]:
    return set(os.environ)


def jardo_home() -> Path:
    """Per-user data directory for the self-contained build (SQLite file, etc.)."""
    return Path.home() / ".jardo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARDO_")

    # Self-contained desktop build: no Postgres/Redis. When true (the packaged
    # app sets JARDO_EMBEDDED=1), the datastore defaults to a SQLite file under
    # ~/.jardo and jobs run in-process. Dev/server default is false → Postgres.
    embedded: bool = False

    # Local dev defaults match infra/docker-compose.yml (localhost-bound).
    database_url: str = "postgresql+asyncpg://jardo:jardo-dev-only@127.0.0.1:5432/jardo"
    redis_url: str = "redis://127.0.0.1:6379/0"

    @model_validator(mode="after")
    def _embedded_datastore(self) -> "Settings":
        # In embedded mode, point at a per-user SQLite file unless the owner set
        # JARDO_DATABASE_URL explicitly (env always wins over this default).
        if self.embedded and "JARDO_DATABASE_URL" not in _env_keys():
            home = jardo_home()
            home.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite+aiosqlite:///{home / 'jardo.db'}"
        return self

    @model_validator(mode="after")
    def _bundled_models(self) -> "Settings":
        # Frozen desktop build: use the voice model shipped inside the app so the
        # first run is offline and instant (no download). JARDO_BUNDLE_DIR is set
        # by the frozen entry point to the bundle's data root.
        bundle = os.environ.get("JARDO_BUNDLE_DIR")
        if bundle and "JARDO_VOICE_PIPER_MODEL" not in _env_keys():
            piper = Path(bundle) / "models" / "piper" / "en_US-hfc_female-medium.onnx"
            if piper.exists():
                self.voice_piper_model = str(piper)
        return self

    # Fireworks OpenAI-compatible endpoint.
    # Source: docs/vendor/fireworks/quickstart-serverless.md
    fireworks_base_url: str = "https://api.fireworks.ai/inference/v1"

    # AMD (self-hosted vLLM on MI300X) — also OpenAI-compatible, so it reuses the
    # same client; only base_url + key differ. Empty until the owner points Jardo
    # at their droplet (Settings → Providers, or JARDO_AMD_BASE_URL). The endpoint
    # is a URL, not a secret; the key lives in the Keychain (secrets.AMD_API_KEY).
    amd_base_url: str = ""
    amd_model: str = "vllm-large"  # model id served by the vLLM endpoint

    # Default chat model = proposed cheap tier (QUESTIONS.md Q4, pending eval
    # validation in Phase 2). Model id format per
    # docs/vendor/fireworks/querying-text-models.md ("accounts/<org>/models/<name>").
    chat_model: str = "accounts/fireworks/models/gpt-oss-20b"
    # Fact-extraction worker uses the same cheap tier until the router exists.
    extraction_model: str = "accounts/fireworks/models/gpt-oss-20b"

    request_timeout_seconds: float = 120.0
    history_window: int = 20  # messages of context sent per chat turn
    # Hard ceiling on chat reply length — the main lever on paid output tokens
    # (spec §5). ~400 tokens is a few concise sentences; raise it if you want
    # longer answers, at higher cost.
    chat_max_tokens: int = 400

    # Phase 1 binds to loopback only; remote access arrives with mTLS in Phase 5.
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Which terminal Jardo reads/answers in (spec §4.3). "terminal" (Terminal.app)
    # and "iterm" are scriptable; Warp / VS Code aren't — for those set it to
    # anything else and supervise Claude via the PreToolUse hook instead.
    supervise_terminal: str = "terminal"

    # Voice (spec §8) — fully optional.
    voice_enabled: bool = False
    voice_tts_backend: str = "piper"  # "piper" (neural, natural) | "say" (macOS)
    voice_tts_voice: str = "Samantha"  # used only by the `say` backend
    voice_piper_model: str = str(
        Path.home() / ".local/share/jardo/piper/en_US-hfc_female-medium.onnx"
    )
    # faster-whisper model. "small.en" is English-only (fast, tuned for native
    # English). For accented / non-native speakers, a MULTILINGUAL model handles
    # accents much better — set JARDO_VOICE_STT_MODEL=medium (or large-v3 for the
    # best accuracy, at CPU-speed cost). The vocabulary prompt in stt.py helps on
    # any model.
    voice_stt_model: str = "small.en"
    # Speed knobs (spec §8): beam_size 1 (greedy) is ~2-3x faster than 5 with a
    # small accuracy cost — worth it for short spoken commands. silence_ms is how
    # long to wait after you stop talking before transcribing.
    voice_stt_beam_size: int = 1
    voice_silence_ms: int = 550
    # Optional noise suppression before STT (noisereduce). Off by default and
    # measured, not assumed — Whisper can do worse on over-denoised audio.
    # Needs the `denoise` extra: uv sync --extra denoise
    voice_denoise: bool = False


settings = Settings()
