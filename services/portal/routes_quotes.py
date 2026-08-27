"""Non-binding public ComputeMesh pricing estimator.

This endpoint is an engineering/UI estimator only. It deliberately does not publish
hyperscaler comparisons, savings percentages, SLAs or a binding production quote.
Binding commercial pricing must come from the approved private quote/order path.
"""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

from services.common.pricing import get_price_tier

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
    """Return a clearly labelled, non-binding engineering estimate."""

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
        prompt_micro = tokens_m * 0.75 * tier.prompt_micro_per_million
        completion_micro = tokens_m * 0.25 * tier.completion_micro_per_million
        total_micro = prompt_micro + completion_micro
        illustrative_total = round(total_micro / 1_000_000, 2)

        return (
            {
                "kind": "illustrative_estimate",
                "binding": False,
                "currency": "USD",
                "tokens_million": tokens_m,
                "model_tier": model_tier,
                "reference_rate_per_million_usd": round(tier.blended_usd_per_million, 4),
                "illustrative_total_usd": illustrative_total,
                # Backwards-compatible field name. Its meaning is explicitly governed by
                # kind=binding=false and the disclaimer; it is not a contractual quote.
                "total_cost_usd": illustrative_total,
                "disclaimer": (
                    "Engineering estimate only; not a binding price, saving, SLA, capacity promise or provider-income guarantee."
                ),
            },
            None,
            HTTPStatus.OK,
        )
