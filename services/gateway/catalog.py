"""ComputeMesh Model Catalog & Pricing Tiers.

Defines available open-weight models, pricing per million tokens,
model alias resolution for OpenAI and Ollama formats, and provider share distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time


@dataclass(frozen=True)
class PriceTier:
    """Pricing configuration in micro-units ($1.00 = 1,000,000 micro-units)."""
    prompt_micro_per_token: int
    completion_micro_per_token: int


@dataclass(frozen=True)
class ModelSpec:
    """Model specification with capabilities and resource requirements."""
    id: str
    owned_by: str = "computemesh"
    context_window: int = 32768
    created: int = 1700000000
    price_tier: PriceTier = PriceTier(100, 300)


DEFAULT_PROVIDER_PERCENTAGE = 0.75  # 75% to hardware providers, 25% platform fee

DEFAULT_PRICE_TIERS: dict[str, PriceTier] = {
    "deepseek-ai/deepseek-r1": PriceTier(prompt_micro_per_token=550, completion_micro_per_token=2190),
    "qwen/qwen2.5-72b-instruct": PriceTier(prompt_micro_per_token=400, completion_micro_per_token=1200),
    "qwen/qwen2.5-7b-instruct": PriceTier(prompt_micro_per_token=100, completion_micro_per_token=300),
    "llama/llama-3.1-70b-instruct": PriceTier(prompt_micro_per_token=600, completion_micro_per_token=1800),
    "meta-llama/llama-3.3-70b-instruct": PriceTier(prompt_micro_per_token=600, completion_micro_per_token=1800),
    "meta-llama/llama-3.1-8b-instruct": PriceTier(prompt_micro_per_token=100, completion_micro_per_token=300),
    "mistralai/mistral-large-2407": PriceTier(prompt_micro_per_token=2000, completion_micro_per_token=6000),
}

AVAILABLE_MODELS: list[ModelSpec] = [
    ModelSpec(
        id="deepseek-ai/deepseek-r1",
        context_window=65536,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["deepseek-ai/deepseek-r1"],
    ),
    ModelSpec(
        id="qwen/qwen2.5-72b-instruct",
        context_window=32768,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["qwen/qwen2.5-72b-instruct"],
    ),
    ModelSpec(
        id="qwen/qwen2.5-7b-instruct",
        context_window=32768,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["qwen/qwen2.5-7b-instruct"],
    ),
    ModelSpec(
        id="llama/llama-3.1-70b-instruct",
        context_window=131072,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["llama/llama-3.1-70b-instruct"],
    ),
    ModelSpec(
        id="meta-llama/llama-3.3-70b-instruct",
        context_window=131072,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["meta-llama/llama-3.3-70b-instruct"],
    ),
    ModelSpec(
        id="meta-llama/llama-3.1-8b-instruct",
        context_window=131072,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["meta-llama/llama-3.1-8b-instruct"],
    ),
    ModelSpec(
        id="mistralai/mistral-large-2407",
        context_window=128000,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["mistralai/mistral-large-2407"],
    ),
]


def resolve_model_id(raw_model: str) -> str:
    """Maps raw model name, Ollama tag (e.g. qwen2.5:7b, llama3.1:8b), or alias to canonical model ID."""
    if not raw_model:
        return AVAILABLE_MODELS[2].id  # default qwen2.5-7b

    model_clean = raw_model.strip().lower()

    # 1. Exact match on full model ID
    for m in AVAILABLE_MODELS:
        if model_clean == m.id.lower():
            return m.id

    def norm(s: str) -> str:
        return s.replace(".", "").replace("-", "").replace("_", "").lower()

    # 2. Tagged alias matching e.g. "qwen2.5:7b", "llama3.1:8b", "llama3.3:70b"
    if ":" in model_clean:
        base, tag = model_clean.split(":", 1)
        for m in AVAILABLE_MODELS:
            short_name = m.id.split("/")[-1].lower()
            if norm(base) in norm(short_name) and norm(tag) in norm(short_name):
                return m.id

    # 3. Direct substring match on short name
    for m in AVAILABLE_MODELS:
        short_name = m.id.split("/")[-1].lower()
        if norm(model_clean) in norm(short_name):
            return m.id

    return AVAILABLE_MODELS[2].id


def provider_shares_from_env() -> list[tuple[str, float]]:
    """Parses COMPUTEMESH_PROVIDER_SHARES env var or returns default provider node."""
    configured = os.environ.get("COMPUTEMESH_PROVIDER_SHARES", "").strip()
    if not configured:
        provider_id = os.environ.get("COMPUTEMESH_DEFAULT_PROVIDER_NODE_ID", "lab-mesh-default-rig").strip()
        if not provider_id:
            raise ValueError("COMPUTEMESH_DEFAULT_PROVIDER_NODE_ID must not be empty")
        return [(provider_id, 1.0)]

    shares: list[tuple[str, float]] = []
    for part in configured.split(","):
        item = part.strip()
        if not item:
            continue
        sep = ":" if ":" in item else "="
        if sep not in item:
            raise ValueError("COMPUTEMESH_PROVIDER_SHARES entries must use provider_id:ratio")
        provider_id, raw_ratio = item.split(sep, 1)
        provider_id = provider_id.strip()
        if not provider_id:
            raise ValueError("COMPUTEMESH_PROVIDER_SHARES contains an empty provider_id")
        try:
            ratio = float(raw_ratio.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid provider ratio for {provider_id}") from exc
        if ratio <= 0:
            raise ValueError(f"Provider ratio for {provider_id} must be positive")
        shares.append((provider_id, ratio))

    if not shares:
        raise ValueError("COMPUTEMESH_PROVIDER_SHARES did not contain any provider entries")
    total = sum(ratio for _, ratio in shares)
    return [(provider_id, ratio / total) for provider_id, ratio in shares]
