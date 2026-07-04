"""Runtime parser for docs/vendor/fireworks/PRICING_TABLE.md (spec §2.1/§5).

The pricing file is the single source of truth for Fireworks serverless prices;
its parsing rules are documented in the file itself. context_window == "RUNTIME"
means unknown until populated from GET /v1/models — the router must not pick a
model with an unknown context window for prompts near any limit.
"""

from dataclasses import dataclass
from pathlib import Path

PRICING_PATH = Path("docs/vendor/fireworks/PRICING_TABLE.md")


@dataclass(frozen=True)
class ModelPrice:
    model_id: str
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float
    context_window: int | None  # None == RUNTIME (not yet known)
    modality: frozenset[str]


class PricingTableError(RuntimeError):
    pass


def load_pricing(path: Path = PRICING_PATH) -> dict[str, ModelPrice]:
    if not path.exists():
        raise PricingTableError(f"pricing table missing: {path} (Phase 0 deliverable)")
    models: dict[str, ModelPrice] = {}
    in_table = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("| model_id |"):
            in_table = True
            continue
        if in_table:
            if not stripped.startswith("|"):
                break  # first table ended
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) != 6 or set(cells[0]) <= {"-", " "}:
                continue
            model_id, in_p, cached_p, out_p, ctx, modality = cells
            model_id = model_id.strip("`")
            try:
                price = ModelPrice(
                    model_id=model_id,
                    input_per_1m=float(in_p),
                    cached_input_per_1m=float(cached_p),
                    output_per_1m=float(out_p),
                    context_window=None if ctx.upper() == "RUNTIME" else int(ctx),
                    modality=frozenset(modality.split("+")),
                )
            except ValueError as exc:
                raise PricingTableError(f"bad row in pricing table: {stripped}") from exc
            models[model_id] = price
    if not models:
        raise PricingTableError(f"no model rows parsed from {path}")
    return models


def estimate_cost_usd(price: ModelPrice, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * price.input_per_1m + output_tokens * price.output_per_1m
    ) / 1_000_000
