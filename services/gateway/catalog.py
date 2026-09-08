"""ComputeMesh Model Catalog & Pricing Tiers.

Defines available open-weight models, pricing per million tokens,
model alias resolution for OpenAI and Ollama formats, and provider share distribution.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import time

from services.common.pricing import (
    DEFAULT_NETWORK_FEE_BPS,
    DEFAULT_PRICE_TIERS,
    DEFAULT_PROVIDER_PERCENTAGE,
    ModelPriceTier,
    calculate_max_charge_micro,
    calculate_token_charge_micro,
    get_price_tier,
)
from services.gateway.registry_client import ModelRegistryClient, RegistryClientError, RegistryModel, build_registry_client_from_env

PriceTier = ModelPriceTier


@dataclass(frozen=True)
class ModelSpec:
    """Model specification with capabilities and resource requirements."""
    id: str
    owned_by: str = "computemesh"
    context_window: int = 32768
    created: int = 1700000000
    price_tier: ModelPriceTier = DEFAULT_PRICE_TIERS["qwen/qwen2.5-7b-instruct"]


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
    ModelSpec(
        id="qwen/qwen2.5-vl-7b-instruct",
        context_window=32768,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["qwen/qwen2.5-vl-7b-instruct"],
    ),
    ModelSpec(
        id="meta-llama/llama-3.2-11b-vision-instruct",
        context_window=131072,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["meta-llama/llama-3.2-11b-vision-instruct"],
    ),
    ModelSpec(
        id="openbmb/minicpm5-2b",
        context_window=32768,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["openbmb/minicpm5-2b"],
    ),
    ModelSpec(
        id="llava/llava-1.6-7b",
        context_window=32768,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["llava/llava-1.6-7b"],
    ),
]

LIVE_MODEL_REGISTRY = build_registry_client_from_env()


def current_models() -> list[ModelSpec | RegistryModel]:
    """Return live public models when configured, otherwise dev catalogue models."""
    if LIVE_MODEL_REGISTRY is None:
        return list(AVAILABLE_MODELS)
    try:
        return list(LIVE_MODEL_REGISTRY.models())
    except RegistryClientError:
        # An explicitly configured registry is authoritative; never advertise
        # stale static or synthetic models after it becomes unavailable.
        return []


def resolve_model_id(raw_model: str) -> str:
    """Maps raw model name, Ollama tag (e.g. qwen2.5:7b, qwen2.5-vl:7b, llama3.1:8b), or alias to canonical model ID."""
    models = current_models()
    live_registry = LIVE_MODEL_REGISTRY is not None
    resolvable_models = [m for m in models if not isinstance(m, RegistryModel) or m.available]
    if not raw_model:
        if live_registry and not resolvable_models:
            raise ValueError("model registry unavailable")
        return resolvable_models[0].id if live_registry else AVAILABLE_MODELS[2].id

    model_clean = raw_model.strip().lower()

    # 1. Exact match on full model ID
    if live_registry and not resolvable_models:
        raise ValueError("model registry unavailable")
    for m in resolvable_models:
        if model_clean == m.id.lower():
            return m.id

    def norm(s: str) -> str:
        return s.replace(".", "").replace("-", "").replace("_", "").lower()

    # 2. Vision model specific aliases (e.g. "qwen2.5-vl:7b", "qwen2.5-vl", "vision", "vision-default", "llava:7b")
    if model_clean in {"vision", "vision-default", "qwen-vl", "qwen2.5-vl", "qwen2.5-vl:7b", "qwen2-vl:7b", "qwen2-vl"}:
        for m in resolvable_models:
            if "vl" in m.id.lower() and "qwen" in m.id.lower():
                return m.id
    if model_clean in {"llama-vision", "llama3.2-vision", "llama3.2-vision:11b", "llama-3.2-vision"}:
        for m in resolvable_models:
            if "vision" in m.id.lower() and "llama" in m.id.lower():
                return m.id
    if model_clean in {"llava", "llava:7b", "llava-1.6", "llava-1.6:7b"}:
        for m in resolvable_models:
            if "llava" in m.id.lower():
                return m.id
    if model_clean in {"minicpm", "minicpm5", "minicpm5-2b", "minicpm-2b", "minicpm5:2b", "minicpm:2b", "openbmb/minicpm5-2b", "openbmb/minicpm-2b"}:
        for m in resolvable_models:
            if "minicpm" in m.id.lower():
                return m.id

    # 3. Tagged alias matching e.g. "qwen2.5:7b", "llama3.1:8b", "llama3.3:70b"
    if ":" in model_clean:
        base, tag = model_clean.split(":", 1)
        for m in resolvable_models:
            short_name = m.id.split("/")[-1].lower()
            if norm(base) in norm(short_name) and norm(tag) in norm(short_name):
                return m.id

    # 4. Direct substring match on short name
    for m in resolvable_models:
        short_name = m.id.split("/")[-1].lower()
        if norm(model_clean) in norm(short_name):
            return m.id

    if live_registry:
        raise ValueError(f"model is not present in the live registry: {raw_model}")
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
