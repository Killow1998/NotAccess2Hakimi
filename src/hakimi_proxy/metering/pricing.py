"""Pricing table and cost computation, modeled after tokscale's approach.

Base prices are per-token (USD). Gemini Free Tier is $0, so these represent
the paid-tier equivalent value used to estimate the dollar value of free usage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from hakimi_proxy.metering.models import TokenBreakdown


@dataclass
class ModelPricing:
    """Per-token pricing for a single model (all values in USD per token)."""

    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    cache_read_input_token_cost: float = 0.0
    cache_creation_input_token_cost: float = 0.0
    reasoning_cost_per_token: float | None = None


_PER_M = 1_000_000.0

BUILTIN_PRICING: dict[str, ModelPricing] = {
    "gemini-3.7-flash": ModelPricing(
        input_cost_per_token=0.75 / _PER_M,
        output_cost_per_token=3.75 / _PER_M,
    ),
    "gemini-3.5-flash": ModelPricing(
        input_cost_per_token=0.30 / _PER_M,
        output_cost_per_token=2.50 / _PER_M,
    ),
    "gemini-3.5-flash-lite": ModelPricing(
        input_cost_per_token=0.30 / _PER_M,
        output_cost_per_token=0.40 / _PER_M,
    ),
    "gemini-3.1-flash-lite": ModelPricing(
        input_cost_per_token=0.10 / _PER_M,
        output_cost_per_token=0.40 / _PER_M,
    ),
    "gemini-3.1-flash-lite-preview": ModelPricing(
        input_cost_per_token=0.10 / _PER_M,
        output_cost_per_token=0.40 / _PER_M,
    ),
    "gemini-3.1-pro-preview": ModelPricing(
        input_cost_per_token=1.25 / _PER_M,
        output_cost_per_token=10.00 / _PER_M,
    ),
    "gemini-3.6-flash": ModelPricing(
        input_cost_per_token=0.30 / _PER_M,
        output_cost_per_token=2.50 / _PER_M,
    ),
    "gemini-2.5-pro": ModelPricing(
        input_cost_per_token=1.25 / _PER_M,
        output_cost_per_token=10.00 / _PER_M,
    ),
    "gemini-2.5-flash": ModelPricing(
        input_cost_per_token=0.30 / _PER_M,
        output_cost_per_token=2.50 / _PER_M,
    ),
    "gemini-2.5-flash-lite": ModelPricing(
        input_cost_per_token=0.10 / _PER_M,
        output_cost_per_token=0.40 / _PER_M,
    ),
    "gemini-2.0-flash": ModelPricing(
        input_cost_per_token=0.10 / _PER_M,
        output_cost_per_token=0.40 / _PER_M,
    ),
    "gemini-2.0-flash-lite": ModelPricing(
        input_cost_per_token=0.075 / _PER_M,
        output_cost_per_token=0.30 / _PER_M,
    ),
}

_pricing_table: dict[str, ModelPricing] = dict(BUILTIN_PRICING)


def load_custom_pricing(path: str | Path) -> None:
    """Load custom pricing overrides from a YAML file."""
    path = Path(path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    for model, vals in raw.items():
        _pricing_table[model] = ModelPricing(
            input_cost_per_token=vals.get("input_cost_per_token", 0.0),
            output_cost_per_token=vals.get("output_cost_per_token", 0.0),
            cache_read_input_token_cost=vals.get("cache_read_input_token_cost", 0.0),
            cache_creation_input_token_cost=vals.get("cache_creation_input_token_cost", 0.0),
            reasoning_cost_per_token=vals.get("reasoning_cost_per_token"),
        )


def get_pricing(model: str) -> ModelPricing | None:
    """Look up pricing for a model, trying exact match then stripped prefix."""
    if model in _pricing_table:
        return _pricing_table[model]
    stripped = model.split("/")[-1]
    if stripped in _pricing_table:
        return _pricing_table[stripped]
    return None


def compute_cost(pricing: ModelPricing, usage: TokenBreakdown) -> float:
    """Compute cost in USD for a token breakdown, replicating tokscale's logic."""
    input_cost = max(usage.input, 0) * pricing.input_cost_per_token
    output_cost = max(usage.output, 0) * pricing.output_cost_per_token
    cache_read_cost = max(usage.cache_read, 0) * pricing.cache_read_input_token_cost
    cache_write_cost = max(usage.cache_write, 0) * pricing.cache_creation_input_token_cost

    reasoning_price = pricing.reasoning_cost_per_token
    if reasoning_price is None:
        reasoning_price = pricing.output_cost_per_token
    reasoning_cost = max(usage.reasoning, 0) * reasoning_price

    return input_cost + output_cost + cache_read_cost + cache_write_cost + reasoning_cost


def compute_cost_for_model(model: str, usage: TokenBreakdown) -> float:
    """Convenience: look up pricing for a model and compute cost."""
    pricing = get_pricing(model)
    if pricing is None:
        return 0.0
    return compute_cost(pricing, usage)
