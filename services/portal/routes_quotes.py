"""ComputeMesh Public Portal Enterprise Quotes & Savings Calculator Handler.

Handles /api/v1/billing/quote for token pricing and hyperscaler cost comparisons.
"""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.common.pricing import (
    DEFAULT_PRICE_TIERS,
    get_price_tier,
)

# Canonical reference map from model tier tag to canonical model ID
TIER_MAP: dict[str, str] = {
    "8b": "meta-llama/llama-3.1-8b-instruct",
    "7b": "qwen/qwen2.5-7b-instruct",
    "14b": "qwen/qwen2.5-14b-instruct",
    "32b": "qwen/qwen2.5-32b-instruct",
    "70b": "llama/llama-3.1-70b-instruct",
    "72b": "qwen/qwen2.5-72b-instruct",
    "r1": "deepseek-ai/deepseek-r1",
    "default": "qwen/qwen2.5-7b-instruct",
}


class PortalQuotesHandler:
    """Calculates enterprise token quotes and cloud savings using canonical pricing."""

    def handle_quote(self, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        try:
            tokens_m = float(body.get("tokens_million", 10.0))
        except (ValueError, TypeError):
            return (None, "Invalid tokens_million format", HTTPStatus.BAD_REQUEST)

        if tokens_m <= 0:
            return (None, "tokens_million must be positive", HTTPStatus.BAD_REQUEST)

        model_tier = str(body.get("model_tier", "8b")).lower()
        canonical_id = TIER_MAP.get(model_tier, TIER_MAP["default"])
        tier = get_price_tier(canonical_id)

        # Integer micro-unit exact math: 75% prompt + 25% completion blended standard
        prompt_micro = tokens_m * 0.75 * tier.prompt_micro_per_million
        completion_micro = tokens_m * 0.25 * tier.completion_micro_per_million
        total_micro = prompt_micro + completion_micro

        cost_usd = round(total_micro / 1_000_000, 2)
        cloud_cost_usd = round(tokens_m * tier.cloud_reference_usd_per_million, 2)
        savings = round(((cloud_cost_usd - cost_usd) / cloud_cost_usd) * 100, 1) if cloud_cost_usd > 0 else 0.0

        return ({
            "tokens_million": tokens_m,
            "model_tier": model_tier,
            "rate_per_million_usd": round(tier.blended_usd_per_million, 4),
            "total_cost_usd": cost_usd,
            "cloud_equivalent_usd": cloud_cost_usd,
            "savings_percent": savings,
        }, None, HTTPStatus.OK)
