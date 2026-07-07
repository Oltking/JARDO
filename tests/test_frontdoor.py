"""Jardo's front-door reply quality (owner: 'premium when a key is set')."""

from core.app import _premium_frontdoor
from core.router.router import RouteDecision


def _local() -> RouteDecision:
    return RouteDecision("ollama", "qwen2.5:0.5b", "trivial", 0.0, 0.0, 0.0,
                         "bootstrap", "local-first")


def _cloud() -> RouteDecision:
    return RouteDecision("fireworks", "fireworks/kimi-k2p6", "critical", 0.01,
                         0.01, 0.0, "ok", "critical")


def test_local_is_upgraded_when_a_key_exists():
    out = _premium_frontdoor(_local(), cloud_ready=True)
    assert out.backend == "fireworks"
    assert out.model != "qwen2.5:0.5b"
    assert out.floor == "premium-frontdoor"


def test_local_stays_local_without_a_key():
    out = _premium_frontdoor(_local(), cloud_ready=False)
    assert out.backend == "ollama"
    assert out.model == "qwen2.5:0.5b"


def test_cloud_route_is_left_alone():
    # Already a strong cloud route (critical) — don't downgrade or touch it.
    out = _premium_frontdoor(_cloud(), cloud_ready=True)
    assert out.model == "fireworks/kimi-k2p6"
