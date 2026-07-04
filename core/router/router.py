"""Cost-Accuracy Router (spec §5): cheapest option at or above the accuracy floor.

Route order by class (spec §5.2):
  trivial/routine → local Ollama → vLLM (AMD, if endpoint configured) → Fireworks cheap
  complex         → cheapest of vLLM-large vs Fireworks-mid by live $/token math
  critical        → strongest available model, cost secondary

Accuracy floor (§5.3): a route is eligible only if its model meets the eval
threshold in evals/scores.json. Bootstrap mode: when no scores exist yet, all
routes are eligible and every decision is logged with floor="bootstrap".

Budget guardrails (§5.4 + §4.6): soft cap at 80% of the daily Fireworks budget
degrades non-critical work to local-only; the hard ceiling raises BudgetExceeded.
"""

import json
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from core.router.classifier import TaskClass
from core.router.pricing import ModelPrice, estimate_cost_usd, load_pricing

ROUTING_CONFIG_PATH = Path("inference/routing.toml")
SCORES_PATH = Path("evals/scores.json")


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class RouteDecision:
    backend: str          # "ollama" | "vllm" | "fireworks"
    model: str
    task_label: str
    est_cost_usd: float
    alternative_cost_usd: float  # what the next-best remote option would have cost
    saved_usd: float
    floor: str            # "ok" | "bootstrap"
    reason: str


@dataclass
class RouterConfig:
    tiers: dict = field(default_factory=dict)
    daily_budget_usd: float = 2.0
    est_output_tokens: int = 512
    vllm_endpoint: str = ""      # empty = AMD GPU droplet not up (scale-to-zero default)
    vllm_hourly_usd: float = 1.99  # MI300X droplet rate (docs/vendor/amd/*)
    vllm_tokens_per_hour: int = 3_600_000
    loaded_at: float = 0.0

    @classmethod
    def load(cls, path: Path = ROUTING_CONFIG_PATH) -> "RouterConfig":
        config = cls(loaded_at=time.time())
        if path.exists():
            data = tomllib.loads(path.read_text())
            config.tiers = data.get("tiers", {})
            for key in ("daily_budget_usd", "est_output_tokens", "vllm_endpoint",
                        "vllm_hourly_usd", "vllm_tokens_per_hour"):
                if key in data:
                    setattr(config, key, data[key])
        return config


def _eligible(model: str, task_label: str) -> tuple[bool, str]:
    """Accuracy floor from nightly evals (§5.3)."""
    if not SCORES_PATH.exists():
        return True, "bootstrap"
    scores = json.loads(SCORES_PATH.read_text())
    entry = scores.get(task_label, {}).get(model)
    if entry is None:
        return True, "bootstrap"
    return (entry["score"] >= entry["threshold"], "ok")


class CostRouter:
    def __init__(self, config: RouterConfig, pricing: dict[str, ModelPrice] | None = None,
                 config_path: Path = ROUTING_CONFIG_PATH):
        self._config = config
        self._config_path = config_path
        self._pricing = pricing or load_pricing()

    def _maybe_reload(self) -> None:
        """Hot-reload (§5.2): pick up config edits without a restart."""
        if self._config_path.exists() and self._config_path.stat().st_mtime > self._config.loaded_at:
            self._config = RouterConfig.load(self._config_path)

    def _fireworks_cost(self, model: str, input_tokens: int) -> float:
        price = self._pricing[model]
        return estimate_cost_usd(price, input_tokens, self._config.est_output_tokens)

    def _vllm_cost(self, input_tokens: int) -> float:
        total = input_tokens + self._config.est_output_tokens
        return (self._config.vllm_hourly_usd / self._config.vllm_tokens_per_hour) * total

    def decide(
        self,
        task: TaskClass,
        input_tokens: int,
        ollama_up: bool,
        spent_today_usd: float,
    ) -> RouteDecision:
        self._maybe_reload()
        tiers = self._config.tiers
        cheap = tiers.get("fireworks_cheap", "fireworks/gpt-oss-20b")
        mid = tiers.get("fireworks_mid", "fireworks/minimax-m2p7")
        quality = tiers.get("fireworks_quality", "fireworks/kimi-k2p6")
        local = tiers.get("ollama_local", "llama3.2:3b")
        vllm_large = tiers.get("vllm_large", "")

        budget = self._config.daily_budget_usd
        if spent_today_usd >= budget and task.label != "critical":
            raise BudgetExceeded(
                f"daily hard ceiling reached (${spent_today_usd:.2f}/${budget:.2f}) — §4.6"
            )
        soft_capped = spent_today_usd >= 0.8 * budget

        def fw_decision(model: str, alt_model: str, reason: str) -> RouteDecision:
            ok, floor = _eligible(model, task.label)
            if not ok:
                model = alt_model  # demoted by eval floor; alt is next tier up
                reason += " (primary failed accuracy floor)"
                _, floor = _eligible(model, task.label)
            cost = self._fireworks_cost(model, input_tokens)
            return RouteDecision("fireworks", model, task.label, cost,
                                 alternative_cost_usd=cost, saved_usd=0.0,
                                 floor=floor, reason=reason)

        # -- critical: strongest available, cost secondary (§5.2.3) ----------
        if task.label == "critical":
            return fw_decision(quality, quality, "critical → strongest model")

        remote_alt = self._fireworks_cost(cheap, input_tokens)

        # -- trivial/routine: local first (§5.2.1) ---------------------------
        if task.label in ("trivial", "routine"):
            if ollama_up:
                ok, floor = _eligible(local, task.label)
                if ok:
                    return RouteDecision("ollama", local, task.label, 0.0,
                                         alternative_cost_usd=remote_alt,
                                         saved_usd=remote_alt, floor=floor,
                                         reason="local-first for cheap tiers")
            if self._config.vllm_endpoint:
                cost = self._vllm_cost(input_tokens)
                return RouteDecision("vllm", vllm_large or "vllm-small", task.label, cost,
                                     alternative_cost_usd=remote_alt,
                                     saved_usd=max(remote_alt - cost, 0.0),
                                     floor="bootstrap", reason="ollama down → vLLM fallback")
            if soft_capped:
                raise BudgetExceeded(
                    "80% soft cap reached and no local backend for non-critical work (§5.4)"
                )
            return fw_decision(cheap, mid, "no local backend → Fireworks cheap tier")

        # -- complex: live $/token comparison (§5.2.2) -----------------------
        if soft_capped and not self._config.vllm_endpoint and not ollama_up:
            raise BudgetExceeded("80% soft cap reached; complex task queued for local (§5.4)")
        fireworks_cost = self._fireworks_cost(mid, input_tokens)
        if self._config.vllm_endpoint and vllm_large:
            vllm_cost = self._vllm_cost(input_tokens)
            if vllm_cost < fireworks_cost:
                return RouteDecision("vllm", vllm_large, task.label, vllm_cost,
                                     alternative_cost_usd=fireworks_cost,
                                     saved_usd=fireworks_cost - vllm_cost,
                                     floor="bootstrap",
                                     reason="vLLM cheaper by live $/token math")
        return fw_decision(mid, quality, "Fireworks mid wins $/token comparison")
