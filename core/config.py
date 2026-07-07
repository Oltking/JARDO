"""Non-secret runtime configuration.

Secrets (API keys, key material) are NEVER configured here — they live in the
macOS Keychain via core.secrets (SECURITY.md rule 3). Everything below is safe
to appear in a process listing.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARDO_")

    # Local dev defaults match infra/docker-compose.yml (localhost-bound).
    database_url: str = "postgresql+asyncpg://jardo:jardo-dev-only@127.0.0.1:5432/jardo"
    redis_url: str = "redis://127.0.0.1:6379/0"

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

    # Phase 1 binds to loopback only; remote access arrives with mTLS in Phase 5.
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Voice (spec §8) — fully optional.
    voice_enabled: bool = False
    voice_tts_backend: str = "piper"  # "piper" (neural, natural) | "say" (macOS)
    voice_tts_voice: str = "Samantha"  # used only by the `say` backend
    voice_piper_model: str = str(
        Path.home() / ".local/share/jardo/piper/en_US-hfc_female-medium.onnx"
    )
    voice_stt_model: str = "small.en"  # faster-whisper model (accuracy vs. speed)
    # Optional neural noise suppression before STT (DeepFilterNet). Off by default
    # and measured, not assumed — Whisper can do worse on over-denoised audio.
    # Needs the `denoise` extra: uv sync --extra denoise
    voice_denoise: bool = False


settings = Settings()
