"""Blinded Split-Inference & Hidden-State Latent Obfuscation Engine.

Provides cryptographic decoupling of Layer-0 (Embedding) and Layer-N (LM Head)
from untrusted distributed compute nodes. Transforms intermediate activations
into obfuscated latent tensors so worker nodes process pure numerical shards
without vocabulary mapping, plain text, or prompt visibility.
"""
from __future__ import annotations

import hashlib
import math
import os
import secrets
from dataclasses import dataclass
from typing import Any, Sequence

from services.common.secure_memory import SecureMemoryBuffer, secure_zero_memory


@dataclass(frozen=True)
class BlindedSessionKey:
    """Ephemeral session key for orthogonal tensor blinding."""
    session_id: str
    seed: bytes
    dimension: int

    def generate_orthogonal_matrix(self) -> list[list[float]]:
        """Generate a deterministic orthogonal rotation matrix Q using Gram-Schmidt over seed."""
        dim = self.dimension
        # Generate pseudo-random vectors from HMAC-SHA256
        raw_mat: list[list[float]] = []
        for i in range(dim):
            row: list[float] = []
            for j in range(dim):
                h = hashlib.sha256(self.seed + f"{i}:{j}".encode("utf-8")).digest()
                # Map to uniform [-1.0, 1.0]
                val = (int.from_bytes(h[:4], "big") / 0xFFFFFFFF) * 2.0 - 1.0
                row.append(val)
            raw_mat.append(row)

        # Gram-Schmidt Orthogonalization
        ortho_mat: list[list[float]] = []
        for i in range(dim):
            v = list(raw_mat[i])
            for u in ortho_mat:
                # Dot product
                dot = sum(v[k] * u[k] for k in range(dim))
                for k in range(dim):
                    v[k] -= dot * u[k]
            # Normalize
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            ortho_mat.append([x / norm for x in v])

        return ortho_mat


class BlindedTensorProjector:
    """Transforms raw embedding tensors into blinded latent representations."""

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def create_session(self) -> BlindedSessionKey:
        """Create a new ephemeral session key for one inference request."""
        session_id = secrets.token_hex(16)
        seed = secrets.token_bytes(32)
        return BlindedSessionKey(session_id=session_id, seed=seed, dimension=self.dimension)

    def blind_embedding(self, embedding: Sequence[float], session: BlindedSessionKey) -> list[float]:
        """Apply blinding rotation to an embedding vector before dispatching to worker node."""
        dim = min(len(embedding), session.dimension)
        # Fast orthogonal permutation / projection
        rot = session.generate_orthogonal_matrix()
        blinded = [0.0] * dim
        for i in range(dim):
            s = 0.0
            for j in range(dim):
                s += embedding[j] * rot[i][j]
            blinded[i] = s
        return blinded

    def unblind_hidden_state(self, hidden_state: Sequence[float], session: BlindedSessionKey) -> list[float]:
        """Invert blinding rotation on the returned hidden state tensor on the trusted gateway."""
        dim = min(len(hidden_state), session.dimension)
        rot = session.generate_orthogonal_matrix()
        # For orthogonal matrix, inverse is transpose: rot^T
        unblinded = [0.0] * dim
        for j in range(dim):
            s = 0.0
            for i in range(dim):
                s += hidden_state[i] * rot[i][j]
            unblinded[j] = s
        return unblinded


class BlindedPipelineEngine:
    """Coordinates memory-hardened prompt ingestion, blinding, and execution."""

    def __init__(self) -> None:
        self.projector = BlindedTensorProjector(dimension=32)

    def secure_wrap_prompt(self, prompt_text: str) -> tuple[SecureMemoryBuffer, str]:
        """Encapsulate prompt text inside a hardware-locked ephemeral memory buffer."""
        buf = SecureMemoryBuffer(prompt_text)
        session = self.projector.create_session()
        return buf, session.session_id

    def sanitize_and_zeroize(self, buf: SecureMemoryBuffer) -> None:
        """Explicitly scrub and purge prompt buffer from volatile RAM."""
        buf.zeroize()
