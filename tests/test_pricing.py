"""Parses the real Phase 0 pricing table — the file the router reads at runtime."""

import pytest

from core.router.pricing import PricingTableError, estimate_cost_usd, load_pricing


def test_loads_real_pricing_table():
    models = load_pricing()
    assert "fireworks/gpt-oss-20b" in models
    cheap = models["fireworks/gpt-oss-20b"]
    assert cheap.input_per_1m == 0.07
    assert cheap.output_per_1m == 0.30
    assert cheap.context_window is None  # RUNTIME sentinel → None until /v1/models


def test_modality_parsing():
    models = load_pricing()
    assert models["fireworks/glm-5p1"].modality == frozenset({"text", "vision"})
    assert models["fireworks/kimi-k2p6"].modality == frozenset({"text"})


def test_cost_estimate_math():
    models = load_pricing()
    price = models["fireworks/gpt-oss-20b"]
    # 1M input + 1M output at documented rates
    assert estimate_cost_usd(price, 1_000_000, 1_000_000) == pytest.approx(0.07 + 0.30)
    # zero tokens costs zero
    assert estimate_cost_usd(price, 0, 0) == 0.0


def test_missing_table_raises(tmp_path):
    with pytest.raises(PricingTableError, match="missing"):
        load_pricing(tmp_path / "nope.md")
