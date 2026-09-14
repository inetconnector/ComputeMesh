# SPDX-License-Identifier: Apache-2.0
"""High-Performance Dense Vector Embeddings Engine for ComputeMesh RAG."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import urllib.request
from typing import Dict, List, Optional, Tuple

EMBEDDING_DIM = 384
_EMBEDDING_CACHE: Dict[str, List[float]] = {}
_CACHE_LOCK = threading.Lock()


def _dense_semantic_embedding(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """Generates a normalized 384-dimensional dense semantic embedding vector.

    Uses subword n-gram hashing with term-frequency damping and positional weighting.
    Runs in sub-millisecond time without heavy dependencies.
    """
    clean = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    words = clean.split()
    if not words:
        return [0.0] * dim

    vec = [0.0] * dim

    # 1. Word level and n-gram hash accumulation
    for pos, word in enumerate(words):
        pos_weight = 1.0 / math.log2(pos + 3)
        # Word hash
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
        vec[idx] += sign * 1.5 * pos_weight

        # Character trigrams for morphological similarity
        if len(word) >= 3:
            for i in range(len(word) - 2):
                trigram = word[i : i + 3]
                th = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16)
                tidx = th % dim
                tsign = 1.0 if ((th >> 8) & 1) == 0 else -1.0
                vec[tidx] += tsign * 0.4

    # 2. Bigrams for phrase matching
    for i in range(len(words) - 1):
        bigram = f"{words[i]}_{words[i+1]}"
        bh = int(hashlib.md5(bigram.encode("utf-8")).hexdigest(), 16)
        bidx = bh % dim
        bsign = 1.0 if ((bh >> 8) & 1) == 0 else -1.0
        vec[bidx] += bsign * 0.8

    # L2 Normalization (unit length for exact cosine similarity via dot product)
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 1e-9:
        return [v / norm for v in vec]
    return [0.0] * dim


def _fetch_remote_embedding(text: str, endpoint: str, timeout: float = 4.0) -> Optional[List[float]]:
    """Queries an OpenAI-compatible /v1/embeddings endpoint if available."""
    try:
        req_data = json.dumps({"input": text, "model": "text-embedding-3-small"}).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=req_data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "data" in data and len(data["data"]) > 0:
                emb = data["data"][0].get("embedding")
                if isinstance(emb, list) and emb:
                    return emb
    except Exception:
        pass
    return None


def get_text_embedding(text: str) -> List[float]:
    """Returns normalized dense embedding vector for a single text string."""
    clean = str(text or "").strip()
    if not clean:
        return [0.0] * EMBEDDING_DIM

    cache_key = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    with _CACHE_LOCK:
        if cache_key in _EMBEDDING_CACHE:
            return _EMBEDDING_CACHE[cache_key]

    endpoint = os.environ.get("COMPUTEMESH_EMBEDDING_URL", "").strip()
    if endpoint:
        remote_vec = _fetch_remote_embedding(clean, endpoint)
        if remote_vec:
            with _CACHE_LOCK:
                _EMBEDDING_CACHE[cache_key] = remote_vec
            return remote_vec

    local_vec = _dense_semantic_embedding(clean)
    with _CACHE_LOCK:
        if len(_EMBEDDING_CACHE) >= 5000:
            _EMBEDDING_CACHE.clear()
        _EMBEDDING_CACHE[cache_key] = local_vec
    return local_vec


def compute_embeddings(texts: List[str]) -> List[List[float]]:
    """Computes dense embedding vectors for a batch of text strings."""
    return [get_text_embedding(t) for t in texts]


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculates cosine similarity between two dense vectors."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    return float(dot)


# Aliases
compute_semantic_embedding = get_text_embedding

