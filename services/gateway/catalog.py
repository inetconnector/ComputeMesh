"""ComputeMesh Model Catalog & Pricing Tiers.

Defines available open-weight models, pricing per million tokens,
model alias resolution for OpenAI and Ollama formats, and provider share distribution.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from urllib import error, request

from services.common.pricing import (
    DEFAULT_NETWORK_FEE_BPS,
    DEFAULT_PRICE_TIERS,
    DEFAULT_PROVIDER_PERCENTAGE,
    ModelPriceTier,
    calculate_max_charge_micro,
    calculate_token_charge_micro,
    get_price_tier,
)
from services.gateway.registry_client import (
    ModelRegistryClient,
    RegistryClientError,
    RegistryModel,
    build_registry_client_from_env,
)

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
    capabilities: tuple[str, ...] = ("completion",)
    availability: str = "catalogued"
    available: bool = True
    display_name: str = ""
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
_RUNTIME_CACHE_LOCK = threading.RLock()
_RUNTIME_CACHE: tuple[float, tuple[ModelSpec, ...]] | None = None


def _runtime_catalog_ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("COMPUTEMESH_RUNTIME_CATALOG_CACHE_SECONDS", "10")))
    except ValueError:
        return 10.0


def _ollama_runtime_models() -> list[ModelSpec] | None:
    """Discover models that the configured Ollama backend can execute now.

    ``None`` means that Ollama is not the configured backend.  An empty list
    means that it is configured but unavailable or internally inconsistent;
    callers must fail closed instead of falling back to synthetic metadata.
    """
    backend = os.environ.get("COMPUTEMESH_INFERENCE_BACKEND", "disabled").strip().lower()
    if backend not in {"ollama", "ollama-http", "ollama_http"}:
        return None
    base_url = os.environ.get("COMPUTEMESH_INFERENCE_URL", "").strip().rstrip("/")
    if not base_url:
        return []

    now = time.monotonic()
    ttl = _runtime_catalog_ttl()
    global _RUNTIME_CACHE
    with _RUNTIME_CACHE_LOCK:
        if _RUNTIME_CACHE is not None and now - _RUNTIME_CACHE[0] < ttl:
            return list(_RUNTIME_CACHE[1])

    try:
        with request.urlopen(
            request.Request(f"{base_url}/api/tags", headers={"Accept": "application/json"}),
            timeout=2.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
        return []

    raw_models = payload.get("models", []) if isinstance(payload, dict) else []
    if not isinstance(raw_models, list):
        return []
    override = os.environ.get("COMPUTEMESH_INFERENCE_MODEL", "").strip()
    discovered: list[ModelSpec] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("name") or raw.get("model") or "").strip()
        if not model_id or (override and model_id != override):
            continue
        try:
            show_request = request.Request(
                f"{base_url}/api/show",
                data=json.dumps({"model": model_id}, separators=(",", ":")).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            with request.urlopen(show_request, timeout=3.0) as response:
                shown = json.loads(response.read().decode("utf-8"))
        except (OSError, error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError):
            continue
        capabilities = tuple(
            str(value).strip().lower().replace("-", "_")
            for value in shown.get("capabilities", [])
            if str(value).strip()
        )
        model_info = shown.get("model_info", {})
        context_window = int(
            os.environ.get("COMPUTEMESH_INFERENCE_CONTEXT_TOKENS", "32768") or 32768
        )
        if isinstance(model_info, dict):
            for key, value in model_info.items():
                if str(key).endswith(".context_length"):
                    try:
                        context_window = max(1, int(value))
                    except (TypeError, ValueError):
                        pass
                    break
        details = shown.get("details", {}) if isinstance(shown.get("details"), dict) else {}
        modalities = ["text"]
        if "vision" in capabilities:
            modalities.append("vision")
        discovered.append(
            ModelSpec(
                id=model_id,
                context_window=context_window,
                created=0,
                price_tier=get_price_tier(model_id),
                modalities=tuple(modalities),
                capabilities=capabilities or ("completion",),
                availability="available_warm",
                available=True,
                display_name=model_id,
                artifact_size_bytes=int(raw.get("size", 0) or 0),
                quantization=str(details.get("quantization_level", "")),
            )
        )

    # A configured override is an execution contract.  If Ollama does not
    # report that exact model, advertise nothing instead of substituting one.
    if override and not discovered:
        return []
    result = tuple(discovered)
    with _RUNTIME_CACHE_LOCK:
        _RUNTIME_CACHE = (now, result)
    return list(result)


def current_models() -> list[ModelSpec | RegistryModel]:
    """Return live public models when configured, otherwise dev catalogue models."""
    if LIVE_MODEL_REGISTRY is not None:
        try:
            return list(LIVE_MODEL_REGISTRY.models())
        except RegistryClientError:
            # An explicitly configured registry is authoritative; never advertise
            # stale static or synthetic models after it becomes unavailable.
            return []
    runtime_models = _ollama_runtime_models()
    if runtime_models is not None:
        return runtime_models
    if os.environ.get("COMPUTEMESH_ALLOW_STATIC_MODEL_CATALOG", "").strip() == "1":
        return list(AVAILABLE_MODELS)
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
    return tuple(
        modality for modality in ("text", "vision", "audio", "video") if modality in modalities
    )


def model_capabilities(model: ModelSpec | RegistryModel) -> tuple[str, ...]:
    """Return the complete normalized runtime capability set."""
    values = (*getattr(model, "capabilities", ()), *model_modalities(model))
    return tuple(
        dict.fromkeys(
            str(value).strip().lower().replace("-", "_") for value in values if str(value).strip()
        )
    )


def model_modality_flags(model: ModelSpec | RegistryModel) -> dict[str, bool]:
    """Return the llama.cpp WebUI capability object for a model."""
    modalities = set(model_modalities(model))
    return {name: name in modalities for name in ("vision", "audio", "video")}


def resolve_model_id(raw_model: str) -> str:
    """Maps raw model name, Ollama tag (e.g. qwen2.5:7b, qwen2.5-vl:7b, llama3.1:8b), or alias to canonical model ID."""
    models = current_models()
    live_catalog = LIVE_MODEL_REGISTRY is not None or _ollama_runtime_models() is not None
    resolvable_models = [m for m in models if not isinstance(m, RegistryModel) or m.available]
    if not raw_model:
        if live_catalog and not resolvable_models:
            raise ValueError("model registry unavailable")
        if os.environ.get("COMPUTEMESH_ALLOW_STATIC_MODEL_CATALOG", "").strip() == "1":
            return AVAILABLE_MODELS[2].id
        if resolvable_models:
            return resolvable_models[0].id
        raise ValueError("no executable model is available")

    model_clean = raw_model.strip().lower()

    # 1. Exact match on full model ID
    if live_catalog and not resolvable_models:
        raise ValueError("model registry unavailable")
    for m in resolvable_models:
        if model_clean == m.id.lower():
            return m.id

    def norm(s: str) -> str:
        return s.replace(".", "").replace("-", "").replace("_", "").lower()

    # 2. Vision model specific aliases (e.g. "qwen2.5-vl:7b", "qwen2.5-vl", "vision", "vision-default", "llava:7b")
    if model_clean in {
        "vision",
        "vision-default",
        "qwen-vl",
        "qwen2.5-vl",
        "qwen2.5-vl:7b",
        "qwen2-vl:7b",
        "qwen2-vl",
    }:
        for m in resolvable_models:
            if "vl" in m.id.lower() and "qwen" in m.id.lower():
                return m.id
    if model_clean in {
        "llama-vision",
        "llama3.2-vision",
        "llama3.2-vision:11b",
        "llama-3.2-vision",
    }:
        for m in resolvable_models:
            if "vision" in m.id.lower() and "llama" in m.id.lower():
                return m.id
    if model_clean in {"llava", "llava:7b", "llava-1.6", "llava-1.6:7b"}:
        for m in resolvable_models:
            if "llava" in m.id.lower():
                return m.id
    if model_clean in {
        "minicpm",
        "minicpm5",
        "minicpm5-2b",
        "minicpm-2b",
        "minicpm5:2b",
        "minicpm:2b",
        "openbmb/minicpm5-2b",
        "openbmb/minicpm-2b",
    }:
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

    raise ValueError(f"model is not available: {raw_model}")


def provider_shares_from_env() -> list[tuple[str, float]]:
    """Parses COMPUTEMESH_PROVIDER_SHARES env var or returns default provider node."""
    configured = os.environ.get("COMPUTEMESH_PROVIDER_SHARES", "").strip()
    if not configured:
        provider_id = os.environ.get(
            "COMPUTEMESH_DEFAULT_PROVIDER_NODE_ID", "lab-mesh-default-rig"
        ).strip()
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
