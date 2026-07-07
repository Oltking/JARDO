"""Provider resolution (spec §5): paste a key, Jardo uses it gracefully."""

from core import secrets
from core.inference import providers


def test_configured_prefers_cheaper_amd_when_both_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_OVERRIDES_PATH", tmp_path / "providers.json")
    keys = {secrets.FIREWORKS_API_KEY: "fw", secrets.AMD_API_KEY: "amd"}
    monkeypatch.setattr(secrets, "read_secret", lambda s: keys.get(s))
    providers.set_base_url("amd", "http://droplet:8000/v1")
    # AMD is self-hosted → preferred first when both keys are present.
    assert providers.configured() == ["amd", "fireworks"]


def test_amd_not_ready_without_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_OVERRIDES_PATH", tmp_path / "providers.json")
    monkeypatch.setattr(secrets, "read_secret",
                        lambda s: "amd" if s == secrets.AMD_API_KEY else None)
    # Key alone isn't enough; a vLLM endpoint is required.
    assert providers.is_ready("amd") is False
    assert providers.configured() == []


def test_only_fireworks_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_OVERRIDES_PATH", tmp_path / "providers.json")
    monkeypatch.setattr(secrets, "read_secret",
                        lambda s: "fw" if s == secrets.FIREWORKS_API_KEY else None)
    assert providers.configured() == ["fireworks"]
    assert providers.is_ready("fireworks") is True


def test_resolve_model_namespaces():
    assert (providers.resolve_model("fireworks", "fireworks/gpt-oss-20b")
            == "accounts/fireworks/models/gpt-oss-20b")
    # AMD serves one configured model regardless of the routed tier id.
    assert providers.resolve_model("amd", "fireworks/kimi-k2p6") == "vllm-large"


def test_base_url_override_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_OVERRIDES_PATH", tmp_path / "providers.json")
    providers.set_base_url("amd", "http://mi300x:8000/v1")
    assert providers.base_url("amd") == "http://mi300x:8000/v1"


def test_status_never_leaks_key(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_OVERRIDES_PATH", tmp_path / "providers.json")
    monkeypatch.setattr(secrets, "read_secret", lambda s: "super-secret")
    snapshot = providers.status()
    blob = str(snapshot)
    assert "super-secret" not in blob
    assert all(set(p) == {"name", "label", "has_key", "base_url", "ready"}
               for p in snapshot)
