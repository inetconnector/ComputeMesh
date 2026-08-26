"""ComputeMesh Canonical Pricing Engine & Model Rate Tiers.

Defines the single source of truth for token pricing, micro-unit conversions,
model specifications, and cost calculations across all platform subsystems.

Units:
- Fiat scale: $1.00 USD = 1,000,000 micro-units (1 micro-unit = $0.000001 USD)
- Token pricing: Rates are defined in USD per 1,000,000 tokens ($/1M) and
  micro-units per 1,000,000 tokens (µ$/1M).
  Example: $0.20 per 1M tokens = 200,000 micro-units per 1M tokens = 0.20 µ$ per token.
- Provider share: 75% of customer billing pool (DEFAULT_PROVIDER_PERCENTAGE = 0.75).
- Platform coordination fee: 25% (DEFAULT_NETWORK_FEE_BPS = 2500).
"""
from __future__ import annotations

from dataclasses import dataclass
import time


MICRO_UNITS_PER_USD: int = 1_000_000
DEFAULT_PROVIDER_PERCENTAGE: float = 0.75
DEFAULT_NETWORK_FEE_BPS: int = 2500  # 25.00%


@dataclass(frozen=True)
class ModelPriceTier:
    """Canonical model pricing tier specified in micro-units per 1,000,000 tokens."""
    model_id: str
    prompt_micro_per_million: int      # e.g., 150_000 µ$ = $0.15 / 1M tokens
    completion_micro_per_million: int  # e.g., 250_000 µ$ = $0.25 / 1M tokens
    cloud_reference_usd_per_million: float = 0.75  # Comparison benchmark for AWS/Azure

    @property
    def prompt_usd_per_million(self) -> float:
        return self.prompt_micro_per_million / MICRO_UNITS_PER_USD

    @property
    def completion_usd_per_million(self) -> float:
        return self.completion_micro_per_million / MICRO_UNITS_PER_USD

    @property
    def prompt_micro_per_token(self) -> int:
        return max(1, self.prompt_micro_per_million // 1_000_000)

    @property
    def completion_micro_per_token(self) -> int:
        return max(1, self.completion_micro_per_million // 1_000_000)

    @property
    def blended_usd_per_million(self) -> float:
        # Standard blended estimate (75% prompt / 25% completion typical workload)
        return (self.prompt_usd_per_million * 0.75) + (self.completion_usd_per_million * 0.25)


# Canonical pricing catalog per model family
DEFAULT_PRICE_TIERS: dict[str, ModelPriceTier] = {
    # 0.5B - 3B Lightweight edge models (e.g., Qwen 2.5 0.5B, 1.5B, 3B)
    "qwen/qwen2.5-0.5b-instruct": ModelPriceTier(
        model_id="qwen/qwen2.5-0.5b-instruct",
        prompt_micro_per_million=50_000,       # $0.05 / 1M
        completion_micro_per_million=150_000,  # $0.15 / 1M
        cloud_reference_usd_per_million=0.30,
    ),
    "qwen/qwen2.5-1.5b-instruct": ModelPriceTier(
        model_id="qwen/qwen2.5-1.5b-instruct",
        prompt_micro_per_million=80_000,       # $0.08 / 1M
        completion_micro_per_million=180_000,  # $0.18 / 1M
        cloud_reference_usd_per_million=0.40,
    ),
    # 7B - 8B Standard models (e.g., Qwen 2.5 7B, LLaMA 3.1 8B)
    "qwen/qwen2.5-7b-instruct": ModelPriceTier(
        model_id="qwen/qwen2.5-7b-instruct",
        prompt_micro_per_million=150_000,      # $0.15 / 1M
        completion_micro_per_million=250_000,  # $0.25 / 1M (~$0.20/1M blended)
        cloud_reference_usd_per_million=0.75,
    ),
    "meta-llama/llama-3.1-8b-instruct": ModelPriceTier(
        model_id="meta-llama/llama-3.1-8b-instruct",
        prompt_micro_per_million=150_000,      # $0.15 / 1M
        completion_micro_per_million=250_000,  # $0.25 / 1M
        cloud_reference_usd_per_million=0.75,
    ),
    "llama/llama-3.1-8b-instruct": ModelPriceTier(
        model_id="llama/llama-3.1-8b-instruct",
        prompt_micro_per_million=150_000,      # $0.15 / 1M
        completion_micro_per_million=250_000,  # $0.25 / 1M
        cloud_reference_usd_per_million=0.75,
    ),
    # 14B - 32B Medium models (e.g., Qwen 2.5 14B, 32B)
    "qwen/qwen2.5-14b-instruct": ModelPriceTier(
        model_id="qwen/qwen2.5-14b-instruct",
        prompt_micro_per_million=300_000,      # $0.30 / 1M
        completion_micro_per_million=600_000,  # $0.60 / 1M
        cloud_reference_usd_per_million=1.50,
    ),
    "qwen/qwen2.5-32b-instruct": ModelPriceTier(
        model_id="qwen/qwen2.5-32b-instruct",
        prompt_micro_per_million=500_000,      # $0.50 / 1M
        completion_micro_per_million=900_000,  # $0.90 / 1M (~$0.70/1M blended)
        cloud_reference_usd_per_million=2.00,
    ),
    # 70B - 72B Flagship models (e.g., LLaMA 3.1 70B, LLaMA 3.3 70B, Qwen 72B)
    "llama/llama-3.1-70b-instruct": ModelPriceTier(
        model_id="llama/llama-3.1-70b-instruct",
        prompt_micro_per_million=1_000_000,    # $1.00 / 1M
        completion_micro_per_million=1_800_000, # $1.80 / 1M (~$1.40/1M blended)
        cloud_reference_usd_per_million=3.50,
    ),
    "meta-llama/llama-3.3-70b-instruct": ModelPriceTier(
        model_id="meta-llama/llama-3.3-70b-instruct",
        prompt_micro_per_million=1_000_000,    # $1.00 / 1M
        completion_micro_per_million=1_800_000, # $1.80 / 1M
        cloud_reference_usd_per_million=3.50,
    ),
    "qwen/qwen2.5-72b-instruct": ModelPriceTier(
        model_id="qwen/qwen2.5-72b-instruct",
        prompt_micro_per_million=1_000_000,    # $1.00 / 1M
        completion_micro_per_million=1_800_000, # $1.80 / 1M
        cloud_reference_usd_per_million=3.50,
    ),
    # DeepSeek Reasoning / Large MoE
    "deepseek-ai/deepseek-r1": ModelPriceTier(
        model_id="deepseek-ai/deepseek-r1",
        prompt_micro_per_million=1_200_000,    # $1.20 / 1M
        completion_micro_per_million=3_000_000, # $3.00 / 1M (~$2.10/1M blended)
        cloud_reference_usd_per_million=6.00,
    ),
    "mistralai/mistral-large-2407": ModelPriceTier(
        model_id="mistralai/mistral-large-2407",
        prompt_micro_per_million=2_000_000,    # $2.00 / 1M
        completion_micro_per_million=6_000_000, # $6.00 / 1M
        cloud_reference_usd_per_million=8.00,
    ),
}

DEFAULT_TIER = DEFAULT_PRICE_TIERS["qwen/qwen2.5-7b-instruct"]


def get_price_tier(model_id: str) -> ModelPriceTier:
    """Resolves price tier for a given model id with graceful fallback."""
    clean_id = model_id.strip().lower()
    if clean_id in DEFAULT_PRICE_TIERS:
        return DEFAULT_PRICE_TIERS[clean_id]
    for k, v in DEFAULT_PRICE_TIERS.items():
        if clean_id.endswith(k.split("/")[-1]) or k.split("/")[-1].startswith(clean_id):
            return v
    return DEFAULT_TIER


def calculate_token_charge_micro(
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    """Calculates integer micro-units charge for a token execution.
    
    Formula: (prompt_tokens * prompt_rate + completion_tokens * completion_rate) // 1_000_000
    Minimum: 1 micro-unit for any non-zero token execution to prevent zero-charge rounding leaks.
    """
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return 0

    tier = get_price_tier(model_id)
    raw_micro = (
        (prompt_tokens * tier.prompt_micro_per_million)
        + (completion_tokens * tier.completion_micro_per_million)
    )
    # Integer division with ceiling for fractional micro-unit rounding protection
    charge = (raw_micro + 999_999) // 1_000_000
    return max(1, charge)


def calculate_max_charge_micro(
    model_id: str,
    prompt_estimate: int,
    max_completion_tokens: int,
) -> int:
    """Calculates the maximum possible charge for upfront credit reservation."""
    return calculate_token_charge_micro(
        model_id=model_id,
        prompt_tokens=max(1, prompt_estimate),
        completion_tokens=max(1, max_completion_tokens),
    )
