"""ComputeMesh Model Catalog & Pricing Tiers.

Defines available open-weight models, pricing per million tokens,
model alias resolution for OpenAI and Ollama formats, and provider share distribution.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

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
    modalities: tuple[str, ...] = ("text",)
    availability: str = "catalogued"
    available: bool = False
    artifact_digest: str = ""
    artifact_size_bytes: int = 0
    quantization: str = ""


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
        modalities=("text", "vision"),
    ),
    ModelSpec(
        id="meta-llama/llama-3.2-11b-vision-instruct",
        context_window=131072,
        created=int(time.time()),
        price_tier=DEFAULT_PRICE_TIERS["meta-llama/llama-3.2-11b-vision-instruct"],
        modalities=("text", "vision"),
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
        modalities=("text", "vision"),
    ),
]

LIVE_MODEL_REGISTRY = build_registry_client_from_env()
_RUNTIME_CACHE_LOCK = threading.Lock()
_RUNTIME_CACHE_AT = 0.0
_RUNTIME_CACHE: tuple[ModelSpec, ...] = ()


def _runtime_models_from_env() -> list[ModelSpec] | None:
    """Return an authoritative local-runtime view, or None when none is configured."""
    backend = os.environ.get("COMPUTEMESH_INFERENCE_BACKEND", "").strip().lower()
    if backend == "synthetic":
        if os.environ.get("COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE", "").strip() != "1":
            return []
        return [replace(model, availability="available_warm", available=True) for model in AVAILABLE_MODELS]
    if backend != "ollama":
        return None

    base_url = os.environ.get("COMPUTEMESH_INFERENCE_URL", "").strip().rstrip("/")
    if not base_url:
        return []
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []

    global _RUNTIME_CACHE_AT, _RUNTIME_CACHE
    now = time.monotonic()
    with _RUNTIME_CACHE_LOCK:
        if now - _RUNTIME_CACHE_AT < 2.0:
            return list(_RUNTIME_CACHE)
    request = urllib.request.Request(
        f"{base_url}/api/tags",
        headers={"Accept": "application/json", "User-Agent": "ComputeMesh-Gateway/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            payload = json.loads(response.read(2 * 1024 * 1024 + 1).decode("utf-8"))
        raw_models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raise ValueError("invalid Ollama model list")
        discovered: list[ModelSpec] = []
        for raw in raw_models:
            if not isinstance(raw, dict):
                continue
            model_id = str(raw.get("name") or raw.get("model") or "").strip()
            if not model_id or len(model_id) > 256:
                continue
            details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
            digest = str(raw.get("digest", "")).lower().removeprefix("sha256:")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                digest = ""
            size = int(raw.get("size", 0) or 0)
            if size < 0:
                size = 0
            lower_id = model_id.lower()
            modalities = ("text", "vision") if any(part in lower_id for part in ("-vl", "vision", "llava")) else ("text",)
            discovered.append(ModelSpec(
                id=model_id,
                created=int(time.time()),
                modalities=modalities,
                availability="available_warm",
                available=True,
                artifact_digest=f"sha256:{digest}" if digest else "",
                artifact_size_bytes=size,
                quantization=str(details.get("quantization_level", "")),
            ))
    except (OSError, TimeoutError, UnicodeError, ValueError, json.JSONDecodeError):
        discovered = []
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_CACHE = tuple(discovered)
        _RUNTIME_CACHE_AT = now
    return discovered


def current_models() -> list[ModelSpec | RegistryModel]:
    """Return authoritative registry/runtime models, else the unavailable catalogue."""
    if LIVE_MODEL_REGISTRY is None:
        runtime_models = _runtime_models_from_env()
        if runtime_models is not None:
            return runtime_models
        return list(AVAILABLE_MODELS)
    try:
        return list(LIVE_MODEL_REGISTRY.models())
    except RegistryClientError:
        # An explicitly configured registry is authoritative; never advertise
        # stale static or synthetic models after it becomes unavailable.
        return []


def model_modalities(model: ModelSpec | RegistryModel) -> tuple[str, ...]:
    """Return normalized, explicitly advertised model input modalities."""
    if isinstance(model, ModelSpec):
        return model.modalities
    capabilities = {value.strip().lower().replace("-", "_") for value in model.capabilities}
    modalities = {"text"}
    if capabilities.intersection({"vision", "image", "images", "image_input", "multimodal"}):
        modalities.add("vision")
    if capabilities.intersection({"audio", "speech", "audio_input", "speech_input"}):
        modalities.add("audio")
    if "video" in capabilities or "video_input" in capabilities:
        modalities.add("video")
    return tuple(modality for modality in ("text", "vision", "audio", "video") if modality in modalities)


def model_modality_flags(model: ModelSpec | RegistryModel) -> dict[str, bool]:
    """Return the llama.cpp WebUI capability object for a model."""
    modalities = set(model_modalities(model))
    return {name: name in modalities for name in ("vision", "audio", "video")}


def resolve_model_id(raw_model: str) -> str:
    """Maps raw model name, Ollama tag (e.g. qwen2.5:7b, qwen2.5-vl:7b, llama3.1:8b), or alias to canonical model ID."""
    models = current_models()
    live_registry = LIVE_MODEL_REGISTRY is not None
    resolvable_models = [m for m in models if bool(getattr(m, "available", False))]
    if not raw_model:
        if not resolvable_models:
            raise ValueError("no inference model is currently available")
        preferred = next((m for m in resolvable_models if m.id == "qwen/qwen2.5-7b-instruct"), None)
        return preferred.id if preferred else resolvable_models[0].id

    model_clean = raw_model.strip().lower()

    # 1. Exact match on full model ID
    if not resolvable_models:
        raise ValueError("no inference model is currently available")
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
    raise ValueError(f"model is not available: {raw_model}")


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
