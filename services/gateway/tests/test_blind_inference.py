"""Unit tests for Blinded Split-Inference & Latent Tensor Obfuscation."""
from __future__ import annotations

import math
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.gateway.blind_inference import (
    BlindedPipelineEngine,
    BlindedSessionKey,
    BlindedTensorProjector,
)


def test_blinded_projector_orthogonality() -> None:
    projector = BlindedTensorProjector(dimension=16)
    session = projector.create_session()

    mat = session.generate_orthogonal_matrix()
    dim = len(mat)
    assert dim == 16

    # Test Q * Q^T = I (Identity matrix)
    for i in range(dim):
        for j in range(dim):
            dot = sum(mat[i][k] * mat[j][k] for k in range(dim))
            if i == j:
                assert math.isclose(dot, 1.0, abs_tol=1e-5), f"Diagonal element [{i},{j}] is {dot}"
            else:
                assert math.isclose(dot, 0.0, abs_tol=1e-5), f"Off-diagonal element [{i},{j}] is {dot}"


def test_blinded_embedding_and_unblinding_reconstruction() -> None:
    projector = BlindedTensorProjector(dimension=8)
    session = projector.create_session()

    # Synthetic latent embedding vector
    original_vector = [0.15, -0.42, 0.88, 1.25, -0.05, 0.63, -1.10, 0.44]

    # Blind the embedding
    blinded = projector.blind_embedding(original_vector, session)
    assert len(blinded) == 8
    # Blinded vector must NOT be identical to the original vector
    assert any(not math.isclose(b, o, abs_tol=1e-3) for b, o in zip(blinded, original_vector))

    # Unblind the hidden state
    unblinded = projector.unblind_hidden_state(blinded, session)
    assert len(unblinded) == 8

    # Must reconstruct the exact original vector
    for orig, restored in zip(original_vector, unblinded):
        assert math.isclose(orig, restored, abs_tol=1e-4)


def test_blinded_pipeline_engine_wrap_and_zeroize() -> None:
    engine = BlindedPipelineEngine()
    prompt = "Confidential business analysis prompt for decentralized mesh"

    buf, session_id = engine.secure_wrap_prompt(prompt)
    assert session_id
    with buf.open_plaintext() as pt:
        assert pt.decode("utf-8") == prompt

    engine.sanitize_and_zeroize(buf)
    assert all(b == 0 for b in buf._ciphertext)
