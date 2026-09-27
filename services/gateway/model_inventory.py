"""Safe public model-inventory contract shared by heartbeat handlers."""

from __future__ import annotations

from typing import Any


def sanitize_model_inventory(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value[:128]:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("model_id") or raw.get("name") or "").strip()
        if not model_id or len(model_id) > 256 or model_id in seen:
            continue
        capabilities = raw.get("capabilities", [])
        if not isinstance(capabilities, list):
            capabilities = []
        normalized_capabilities = [
            str(item).strip().lower().replace("-", "_")[:64]
            for item in capabilities[:32]
            if str(item).strip()
        ]
        try:
            context_window = max(0, min(int(raw.get("context_window", 0) or 0), 16_777_216))
            size_bytes = max(0, min(int(raw.get("size_bytes", 0) or 0), 2**50))
        except (TypeError, ValueError):
            continue
        availability = str(raw.get("availability", "unavailable"))
        if availability not in {
            "available_warm",
            "available_cold",
            "warming",
            "unavailable",
            "draining",
        }:
            availability = "unavailable"
        result.append(
            {
                "model_id": model_id,
                "capabilities": normalized_capabilities,
                "context_window": context_window,
                "size_bytes": size_bytes,
                "parameter_size": str(raw.get("parameter_size", ""))[:64],
                "quantization": str(raw.get("quantization_level") or raw.get("quantization") or "")[
                    :64
                ],
                "availability": availability,
            }
        )
        seen.add(model_id)
    return result


__all__ = ["sanitize_model_inventory"]
