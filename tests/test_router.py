import json

import pytest

import core.router.router as router_module
from core.router.classifier import TaskClass
from core.router.pricing import ModelPrice
from core.router.router import BudgetExceeded, CostRouter, RouterConfig


def _pricing():
    def price(mid, inp, out):
        return ModelPrice(mid, inp, inp / 5, out, None, frozenset({"text"}))
    return {
        "fireworks/gpt-oss-20b": price("fireworks/gpt-oss-20b", 0.07, 0.30),
        "fireworks/minimax-m2p7": price("fireworks/minimax-m2p7", 0.30, 1.20),
        "fireworks/kimi-k2p6": price("fireworks/kimi-k2p6", 0.95, 4.00),
    }


def _router(tmp_path, **overrides) -> CostRouter:
    config = RouterConfig(
        tiers={"ollama_local": "llama3.2:3b", "vllm_large": "",
               "fireworks_cheap": "fireworks/gpt-oss-20b",
               "fireworks_mid": "fireworks/minimax-m2p7",
               "fireworks_quality": "fireworks/kimi-k2p6"},
        loaded_at=9e12,  # far future → hot-reload never triggers in tests
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return CostRouter(config, pricing=_pricing(), config_path=tmp_path / "routing.toml")


def _task(label):
    return TaskClass(label, "text", "test")


def test_trivial_prefers_local_and_logs_savings(tmp_path):
    decision = _router(tmp_path).decide(_task("trivial"), 1000, ollama_up=True,
                                        spent_today_usd=0.0)
    assert decision.backend == "ollama"
    assert decision.est_cost_usd == 0.0
    assert decision.saved_usd > 0  # vs Fireworks cheap tier


def test_trivial_without_local_goes_fireworks_cheap(tmp_path):
    decision = _router(tmp_path).decide(_task("trivial"), 1000, ollama_up=False,
                                        spent_today_usd=0.0)
    assert (decision.backend, decision.model) == ("fireworks", "fireworks/gpt-oss-20b")


def test_critical_takes_quality_regardless_of_cost(tmp_path):
    decision = _router(tmp_path).decide(_task("critical"), 1000, ollama_up=True,
                                        spent_today_usd=0.0)
    assert (decision.backend, decision.model) == ("fireworks", "fireworks/kimi-k2p6")


def test_complex_compares_vllm_when_endpoint_up(tmp_path):
    router = _router(tmp_path, vllm_endpoint="http://gpu:8000/v1",
                     vllm_hourly_usd=1.99, vllm_tokens_per_hour=100_000_000)
    router._config.tiers["vllm_large"] = "llama-70b"
    decision = router.decide(_task("complex"), 1000, ollama_up=False, spent_today_usd=0.0)
    assert decision.backend == "vllm"
    assert decision.saved_usd > 0


def test_complex_without_vllm_uses_fireworks_mid(tmp_path):
    decision = _router(tmp_path).decide(_task("complex"), 1000, ollama_up=False,
                                        spent_today_usd=0.0)
    assert (decision.backend, decision.model) == ("fireworks", "fireworks/minimax-m2p7")


def test_hard_budget_ceiling_blocks_noncritical(tmp_path):
    with pytest.raises(BudgetExceeded, match="hard ceiling"):
        _router(tmp_path, daily_budget_usd=2.0).decide(
            _task("routine"), 1000, ollama_up=True, spent_today_usd=2.0)


def test_hard_ceiling_never_blocks_critical(tmp_path):
    decision = _router(tmp_path, daily_budget_usd=2.0).decide(
        _task("critical"), 1000, ollama_up=False, spent_today_usd=99.0)
    assert decision.backend == "fireworks"  # §5.2: critical, cost secondary


def test_soft_cap_degrades_to_local(tmp_path):
    decision = _router(tmp_path, daily_budget_usd=2.0).decide(
        _task("routine"), 1000, ollama_up=True, spent_today_usd=1.8)
    assert decision.backend == "ollama"
    with pytest.raises(BudgetExceeded, match="soft cap"):
        _router(tmp_path, daily_budget_usd=2.0).decide(
            _task("routine"), 1000, ollama_up=False, spent_today_usd=1.8)


def test_accuracy_floor_demotes_failing_model(tmp_path, monkeypatch):
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps({
        "routine": {"fireworks/gpt-oss-20b": {"score": 0.4, "threshold": 0.7, "n": 10}}
    }))
    monkeypatch.setattr(router_module, "SCORES_PATH", scores)
    decision = _router(tmp_path).decide(_task("routine"), 1000, ollama_up=False,
                                        spent_today_usd=0.0)
    assert decision.model == "fireworks/minimax-m2p7"  # demoted off failing cheap tier
    assert "accuracy floor" in decision.reason
