#!/usr/bin/env python3
"""ComputeMesh Dynamic Multi-Model Hot-Swapping & LRU VRAM Cache Manager.

Manages dynamic loading, eviction, and memory caching of large language models
across distributed provider GPU rigs, maximizing VRAM hit ratios and minimizing
cold-start layer transfer latencies.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class ModelCacheError(Exception):
    """Raised when model size exceeds total cluster VRAM capacity."""


@dataclass(frozen=True)
class CachedModelMetadata:
    model_id: str
    weight_bytes: int
    total_layers: int
    is_pinned: bool = False


@dataclass
class LoadedModelEntry:
    model_id: str
    weight_bytes: int
    total_layers: int
    last_accessed_utc: float
    is_pinned: bool = False
    active_inferences: int = 0


class DynamicModelCacheManager:
    def __init__(
        self,
        total_rig_vram_bytes: int,
        usable_memory_fraction: float = 0.90,
    ) -> None:
        self.total_rig_vram_bytes = total_rig_vram_bytes
        self.usable_vram_bytes = int(total_rig_vram_bytes * usable_memory_fraction)
        self.loaded_models: OrderedDict[str, LoadedModelEntry] = OrderedDict()
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.evictions: int = 0

    @property
    def used_vram_bytes(self) -> int:
        return sum(m.weight_bytes for m in self.loaded_models.values())

    @property
    def free_vram_bytes(self) -> int:
        return max(0, self.usable_vram_bytes - self.used_vram_bytes)

    def request_model(
        self,
        model_meta: CachedModelMetadata,
        now_utc: float | None = None,
    ) -> dict[str, Any]:
        """Ensures the model is loaded into VRAM, evicting cold models if necessary."""
        now = now_utc if now_utc is not None else datetime.now(timezone.utc).timestamp()
        model_id = model_meta.model_id

        if model_meta.weight_bytes > self.usable_vram_bytes:
            raise ModelCacheError(
                f"Model {model_id} footprint ({model_meta.weight_bytes / (1024**3):.2f} GB) "
                f"exceeds total usable VRAM ({self.usable_vram_bytes / (1024**3):.2f} GB)"
            )

        # 1. Cache Hit
        if model_id in self.loaded_models:
            entry = self.loaded_models[model_id]
            entry.last_accessed_utc = now
            entry.active_inferences += 1
            self.loaded_models.move_to_end(model_id)
            self.cache_hits += 1
            return {
                "action": "hit",
                "model_id": model_id,
                "used_vram_gb": round(self.used_vram_bytes / (1024**3), 2),
                "free_vram_gb": round(self.free_vram_bytes / (1024**3), 2),
                "evicted": [],
            }

        # 2. Cache Miss: Evict cold unpinned models until sufficient space exists
        self.cache_misses += 1
        evicted_models = []

        while self.free_vram_bytes < model_meta.weight_bytes:
            # Find oldest unpinned and idle model to evict
            evict_candidate_id = None
            for mid, m in self.loaded_models.items():
                if not m.is_pinned and m.active_inferences == 0:
                    evict_candidate_id = mid
                    break

            if not evict_candidate_id:
                raise ModelCacheError("Cannot load model: all loaded models are either pinned or actively serving inference.")

            del self.loaded_models[evict_candidate_id]
            evicted_models.append(evict_candidate_id)
            self.evictions += 1

        # Load new model into cache
        new_entry = LoadedModelEntry(
            model_id=model_id,
            weight_bytes=model_meta.weight_bytes,
            total_layers=model_meta.total_layers,
            last_accessed_utc=now,
            is_pinned=model_meta.is_pinned,
            active_inferences=1,
        )
        self.loaded_models[model_id] = new_entry

        return {
            "action": "loaded",
            "model_id": model_id,
            "used_vram_gb": round(self.used_vram_bytes / (1024**3), 2),
            "free_vram_gb": round(self.free_vram_bytes / (1024**3), 2),
            "evicted": evicted_models,
        }

    def release_model_inference(self, model_id: str) -> None:
        if model_id in self.loaded_models:
            self.loaded_models[model_id].active_inferences = max(0, self.loaded_models[model_id].active_inferences - 1)
