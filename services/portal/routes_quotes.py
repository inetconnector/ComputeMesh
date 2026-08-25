"""ComputeMesh Public Portal Enterprise Quotes & Savings Calculator Handler.

Handles /api/v1/billing/quote for token pricing and hyperscaler cost comparisons.
"""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

# Pricing matrix: ComputeMesh price vs Centralized Cloud Baseline ($ per 1M tokens)
PRICE_RATES: dict[str, tuple[float, float]] = {
    "8b": (0.15, 0.75),      # $0.15 vs $0.75 on AWS Bedrock / Azure
    "70b": (0.75, 3.50),     # $0.75 vs $3.50 on Cloud
    "r1": (1.20, 6.00),      # $1.20 vs $6.00 on DeepSeek Official API
    "default": (0.30, 1.50),
}


class PortalQuotesHandler:
    """Calculates enterprise token quotes and cloud savings."""

    def handle_quote(self, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, HTTPStatus]:
        try:
            tokens_m = float(body.get("tokens_million", 10.0))
        except (ValueError, TypeError):
            return (None, "Invalid tokens_million format", HTTPStatus.BAD_REQUEST)

        if tokens_m <= 0:
            return (None, "tokens_million must be positive", HTTPStatus.BAD_REQUEST)

        model_tier = str(body.get("model_tier", "8b")).lower()
        rate, cloud_rate = PRICE_RATES.get(model_tier, PRICE_RATES["default"])

        cost_usd = round(tokens_m * rate, 2)
        cloud_cost_usd = round(tokens_m * cloud_rate, 2)
        savings = round(((cloud_cost_usd - cost_usd) / cloud_cost_usd) * 100, 1) if cloud_cost_usd > 0 else 0.0

        return ({
            "tokens_million": tokens_m,
            "model_tier": model_tier,
            "rate_per_million_usd": rate,
            "total_cost_usd": cost_usd,
            "cloud_equivalent_usd": cloud_cost_usd,
            "savings_percent": savings,
        }, None, HTTPStatus.OK)
