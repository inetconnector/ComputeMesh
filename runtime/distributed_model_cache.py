"""ComputeMesh Distributed Model Cache Manager.

Manages distributed GGUF/model shard caching, chunk distribution, integrity validation,
prefetching, and cache eviction policies across P2P mesh nodes.
"""
from __future__ import annotations

import os
import time
import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from multiprocessing import shared_memory

log = logging.getLogger("computemesh.runtime.distributed_cache")


@dataclass
class ModelChunkMetadata:
    chunk_index: int
    chunk_size_bytes: int
    sha256_hash: str
    stored_path: str = ""
    is_available_locally: bool = False


@dataclass
class CachedModelShardManifest:
    model_id: str
    total_size_bytes: int
    chunk_size_bytes: int
    total_chunks: int
    sha256_hash: str
    merkle_root: str = ""
    chunks: list[ModelChunkMetadata] = field(default_factory=list)
    last_accessed: float = field(default_factory=time.time)
    is_pinned: bool = False


def compute_merkle_root(chunk_hashes: list[str]) -> str:
    """Computes a cryptographic Merkle root from a list of chunk hashes."""
    if not chunk_hashes:
        return ""
    if len(chunk_hashes) == 1:
        return chunk_hashes[0]

    current_level = chunk_hashes[:]
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            combined = left + right
            next_level.append(hashlib.sha256(combined.encode()).hexdigest())
        current_level = next_level
    return current_level[0]


class DistributedModelCache:
    """Production P2P distributed model cache engine."""

    def __init__(self, cache_dir: Path | str | None = None, max_cache_bytes: int = 100 * 1024 * 1024 * 1024) -> None:
        if cache_dir is None:
            cache_dir = Path(os.environ.get("COMPUTEMESH_MODEL_STORAGE_DIR", "/tmp/computemesh_model_cache"))
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_bytes = max_cache_bytes
        self._lock = threading.Lock()
        self._manifests: dict[str, CachedModelShardManifest] = {}
        self._scan_cache()

    def _scan_cache(self) -> None:
        with self._lock:
            for manifest_file in self.cache_dir.glob("*.manifest.json"):
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    model_id = data["model_id"]
                    chunks = [ModelChunkMetadata(**c) for c in data.get("chunks", [])]
                    manifest = CachedModelShardManifest(
                        model_id=model_id,
                        total_size_bytes=data["total_size_bytes"],
                        chunk_size_bytes=data["chunk_size_bytes"],
                        total_chunks=data["total_chunks"],
                        sha256_hash=data["sha256_hash"],
                        chunks=chunks,
                        last_accessed=data.get("last_accessed", time.time()),
                        is_pinned=data.get("is_pinned", False),
                    )
                    self._manifests[model_id] = manifest
                except Exception as exc:
                    log.warning("Failed to parse cache manifest %s: %s", manifest_file, exc)

    def register_model_shard(
        self,
        model_id: str,
        total_size_bytes: int,
        chunks_data: list[tuple[int, bytes]],
        sha256_hash: str = "",
        is_pinned: bool = False,
    ) -> CachedModelShardManifest:
        model_safe_name = hashlib.sha256(model_id.encode()).hexdigest()[:16]
        model_sub_dir = self.cache_dir / model_safe_name
        model_sub_dir.mkdir(parents=True, exist_ok=True)

        chunk_metas: list[ModelChunkMetadata] = []
        for idx, chunk_bytes in chunks_data:
            chunk_hash = hashlib.sha256(chunk_bytes).hexdigest()
            chunk_file = model_sub_dir / f"chunk_{idx}.bin"
            chunk_file.write_bytes(chunk_bytes)
            chunk_metas.append(
                ModelChunkMetadata(
                    chunk_index=idx,
                    chunk_size_bytes=len(chunk_bytes),
                    sha256_hash=chunk_hash,
                    stored_path=str(chunk_file),
                    is_available_locally=True,
                )
            )

        if not sha256_hash:
            overall_hasher = hashlib.sha256()
            for _, cb in chunks_data:
                overall_hasher.update(cb)
            sha256_hash = overall_hasher.hexdigest()

        # Compute Merkle root from chunks
        chunk_hashes = [m.sha256_hash for m in chunk_metas]
        merkle_root = compute_merkle_root(chunk_hashes)

        manifest = CachedModelShardManifest(
            model_id=model_id,
            total_size_bytes=total_size_bytes,
            chunk_size_bytes=chunks_data[0][1].__len__() if chunks_data else 0,
            total_chunks=len(chunks_data),
            sha256_hash=sha256_hash,
            merkle_root=merkle_root,
            chunks=chunk_metas,
            last_accessed=time.time(),
            is_pinned=is_pinned,
        )

        manifest_file = self.cache_dir / f"{model_safe_name}.manifest.json"
        manifest_file.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")

        with self._lock:
            self._manifests[model_id] = manifest
            self._enforce_eviction_policy()

        return manifest

    def get_model_shard(self, model_id: str) -> CachedModelShardManifest | None:
        with self._lock:
            manifest = self._manifests.get(model_id)
            if manifest:
                manifest.last_accessed = time.time()
                return manifest
            return None

    def pin_model_shard(self, model_id: str, pinned: bool = True) -> bool:
        with self._lock:
            manifest = self._manifests.get(model_id)
            if not manifest:
                return False
            manifest.is_pinned = pinned
            model_safe_name = hashlib.sha256(model_id.encode()).hexdigest()[:16]
            manifest_file = self.cache_dir / f"{model_safe_name}.manifest.json"
            manifest_file.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
            return True

    def verify_shard_integrity(self, model_id: str) -> dict[str, Any]:
        with self._lock:
            manifest = self._manifests.get(model_id)
            if not manifest:
                return {"valid": False, "reason": f"Model shard {model_id} not found in cache"}

            corrupted_chunks = []
            missing_chunks = []
            for chunk in manifest.chunks:
                p = Path(chunk.stored_path)
                if not p.exists():
                    missing_chunks.append(chunk.chunk_index)
                    continue
                file_hash = hashlib.sha256(p.read_bytes()).hexdigest()
                if file_hash != chunk.sha256_hash:
                    corrupted_chunks.append(chunk.chunk_index)

            # Verify Merkle root
            chunk_hashes = [c.sha256_hash for c in manifest.chunks]
            computed_merkle_root = compute_merkle_root(chunk_hashes)
            merkle_valid = manifest.merkle_root == computed_merkle_root if manifest.merkle_root else True
            if not merkle_valid:
                log.warning("Merkle root mismatch for shard %s: expected %s, got %s", model_id, manifest.merkle_root, computed_merkle_root)

            is_valid = len(corrupted_chunks) == 0 and len(missing_chunks) == 0 and merkle_valid
            return {
                "valid": is_valid,
                "model_id": model_id,
                "total_chunks": manifest.total_chunks,
                "missing_chunks": missing_chunks,
                "corrupted_chunks": corrupted_chunks,
                "merkle_valid": merkle_valid,
                "verified_at": time.time(),
            }

    def get_missing_chunks(self, model_id: str, total_chunks: int) -> list[int]:
        with self._lock:
            manifest = self._manifests.get(model_id)
            if not manifest:
                return list(range(total_chunks))
            existing_indices = {c.chunk_index for c in manifest.chunks if c.is_available_locally and Path(c.stored_path).exists()}
            return [i for i in range(total_chunks) if i not in existing_indices]

    def _enforce_eviction_policy(self) -> None:
        """LRU Eviction when cached data exceeds max_cache_bytes, skipping pinned models."""
        total_bytes = sum(m.total_size_bytes for m in self._manifests.values())
        if total_bytes <= self.max_cache_bytes:
            return

        sorted_manifests = sorted(
            [m for m in self._manifests.values() if not m.is_pinned],
            key=lambda m: m.last_accessed,
        )
        for m in sorted_manifests:
            if total_bytes <= self.max_cache_bytes:
                break
            self.remove_model_shard(m.model_id)
            total_bytes -= m.total_size_bytes

    def remove_model_shard(self, model_id: str) -> bool:
        with self._lock:
            manifest = self._manifests.pop(model_id, None)
            if not manifest:
                return False
            model_safe_name = hashlib.sha256(model_id.encode()).hexdigest()[:16]
            manifest_file = self.cache_dir / f"{model_safe_name}.manifest.json"
            if manifest_file.exists():
                manifest_file.unlink()
            model_sub_dir = self.cache_dir / model_safe_name
            if model_sub_dir.exists():
                for f in model_sub_dir.glob("*"):
                    f.unlink()
                model_sub_dir.rmdir()
            return True

    def clear_all(self) -> None:
        with self._lock:
            keys = list(self._manifests.keys())
            for k in keys:
                self.remove_model_shard(k)

    def get_cache_summary(self) -> dict[str, Any]:
        with self._lock:
            cached_models = []
            total_used_bytes = 0
            for m in self._manifests.values():
                total_used_bytes += m.total_size_bytes
                cached_models.append(
                    {
                        "model_id": m.model_id,
                        "size_gb": round(m.total_size_bytes / (1024**3), 3),
                        "chunks_count": len(m.chunks),
                        "last_accessed": m.last_accessed,
                        "is_pinned": m.is_pinned,
                        "hash": m.sha256_hash,
                    }
                )

            return {
                "total_cached_models": len(cached_models),
                "total_used_bytes": total_used_bytes,
                "total_used_gb": round(total_used_bytes / (1024**3), 3),
                "max_cache_gb": round(self.max_cache_bytes / (1024**3), 3),
                "models": cached_models,
            }


GLOBAL_DISTRIBUTED_MODEL_CACHE = DistributedModelCache()


class OffHeapCacheManager:
    """Manages decentralized off-heap caching using multiprocessing shared memory."""

    def __init__(self, max_quota_bytes: int):
        self.max_quota_bytes = max_quota_bytes
        self._lock = threading.Lock()
        self._used_quota = 0
        self._chunks: dict[str, dict[str, Any]] = {}

    def allocate_chunk(self, chunk_id: str, data: bytes) -> bool:
        size = len(data)
        with self._lock:
            if chunk_id in self._chunks:
                return False
            if self._used_quota + size > self.max_quota_bytes:
                return False
            self._used_quota += size

        try:
            shm = shared_memory.SharedMemory(create=True, size=size)
            shm.buf[:size] = data
            with self._lock:
                # Retain open shm handle to prevent Windows from releasing the named mapping early
                self._chunks[chunk_id] = {"shm": shm, "shm_name": shm.name, "size": size}
            return True
        except Exception as e:
            with self._lock:
                self._used_quota -= size
            log.warning("Failed to allocate off-heap memory for %s: %s", chunk_id, e)
            return False

    def read_chunk(self, chunk_id: str) -> bytes | None:
        with self._lock:
            if chunk_id not in self._chunks:
                return None
            info = self._chunks[chunk_id]
            shm = info.get("shm")
            size = info["size"]
            if shm is not None:
                return bytes(shm.buf[:size])
            shm_name = info["shm_name"]

        try:
            shm = shared_memory.SharedMemory(name=shm_name)
            data = bytes(shm.buf[:size])
            shm.close()
            return data
        except Exception as e:
            log.warning("Failed to read off-heap memory for %s: %s", chunk_id, e)
            return None

    def free_chunk(self, chunk_id: str) -> None:
        with self._lock:
            if chunk_id not in self._chunks:
                return
            info = self._chunks.pop(chunk_id)
            shm = info.get("shm")
            shm_name = info["shm_name"]
            size = info["size"]
            self._used_quota -= size

        try:
            if shm is not None:
                shm.close()
                shm.unlink()
            else:
                s = shared_memory.SharedMemory(name=shm_name)
                s.close()
                s.unlink()
        except Exception as e:
            log.warning("Failed to free off-heap memory for %s: %s", chunk_id, e)

    def get_used_quota(self) -> int:
        with self._lock:
            return self._used_quota
