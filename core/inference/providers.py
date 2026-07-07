"""Cloud inference providers (spec §5).

Jardo is provider-agnostic: the owner pastes a Fireworks key and/or an AMD
(self-hosted vLLM / MI300X) endpoint + key, and Jardo uses whichever is
configured — falling back gracefully so a missing key never 500s. Both providers
speak the OpenAI-compatible chat-completions protocol, so a single client
(FireworksClient) serves both; only base_url, key, and model-id namespace differ.

Keys live in the Keychain (core.secrets). The AMD *endpoint* is a URL, not a
secret, so it lives in a 0600 JSON file the desktop Settings panel can write
(~/.jardo/providers.json), overriding the env default (JARDO_AMD_BASE_URL).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from core import secrets
from core.config import settings

_OVERRIDES_PATH = Path.home() / ".jardo" / "providers.json"


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    secret_service: str


FIREWORKS = Provider("fireworks", "Fireworks AI", secrets.FIREWORKS_API_KEY)
AMD = Provider("amd", "AMD (vLLM / MI300X)", secrets.AMD_API_KEY)

PROVIDERS: dict[str, Provider] = {p.name: p for p in (FIREWORKS, AMD)}

# When a route just needs "some cloud model", prefer the cheapest first. AMD is
# self-hosted (flat droplet cost) so it wins when both keys are present.
PREFERENCE: tuple[str, ...] = ("amd", "fireworks")


def _overrides() -> dict:
    try:
        return json.loads(_OVERRIDES_PATH.read_text())
    except (OSError, ValueError):
        return {}


def set_base_url(name: str, url: str) -> None:
    """Persist a runtime endpoint override (used by the Settings panel)."""
    if name not in PROVIDERS:
        raise KeyError(name)
    data = _overrides()
    data.setdefault(name, {})["base_url"] = url.strip()
    _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OVERRIDES_PATH.write_text(json.dumps(data, indent=2))


def base_url(name: str) -> str:
    override = _overrides().get(name, {}).get("base_url")
    if override:
        return override
    return settings.amd_base_url if name == "amd" else settings.fireworks_base_url


def has_key(name: str) -> bool:
    return bool(secrets.read_secret(PROVIDERS[name].secret_service))


def is_ready(name: str) -> bool:
    """A provider is usable only when it has both a key and an endpoint."""
    return has_key(name) and bool(base_url(name))


def configured() -> list[str]:
    """Ready providers, in cost-preference order."""
    return [n for n in PREFERENCE if is_ready(n)]


def api_key(name: str) -> str | None:
    return secrets.read_secret(PROVIDERS[name].secret_service)


def resolve_model(name: str, model: str) -> str:
    """Translate a routed model id into the provider's namespace."""
    if name == "fireworks" and model.startswith("fireworks/"):
        return "accounts/fireworks/models/" + model.removeprefix("fireworks/")
    if name == "amd":
        # The router may hand us a fireworks-tier id; AMD serves one configured
        # model, so map anything non-native onto it.
        return model if model == settings.amd_model else settings.amd_model
    return model


def status() -> list[dict]:
    """Non-secret snapshot for the Settings UI — never returns the key itself."""
    return [
        {
            "name": p.name,
            "label": p.label,
            "has_key": has_key(p.name),
            "base_url": base_url(p.name),
            "ready": is_ready(p.name),
        }
        for p in PROVIDERS.values()
    ]
