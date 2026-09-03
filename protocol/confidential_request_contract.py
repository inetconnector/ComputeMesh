"""Canonical protected-request contract commitment for confidential OpenAI jobs.

The contract digest is embedded into the fresh attestation nonce. Because that
nonce is already authenticated by vendor attestation and included in the
confidential envelope AAD, model and reserved token limits become cryptographically
bound without introducing another user-visible API or leaking prompt contents.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets


CONTRACT_SCHEMA_VERSION = 1
ATTESTATION_NONCE_PREFIX = "cmrc1"
MAX_MODEL_ID_BYTES = 512
MAX_TOKEN_LIMIT = 1_000_000
MIN_NONCE_ENTROPY_BYTES = 16


class ConfidentialRequestContractError(ValueError):
    """Raised when a protected request contract or committed nonce is invalid."""


def _validate_contract_values(
    model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
) -> tuple[str, int, int]:
    model = str(model_id or "").strip()
    if not model or len(model.encode("utf-8")) > MAX_MODEL_ID_BYTES:
        raise ConfidentialRequestContractError("invalid protected model_id")
    for name, value in (
        ("max_prompt_tokens", max_prompt_tokens),
        ("max_completion_tokens", max_completion_tokens),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_TOKEN_LIMIT:
            raise ConfidentialRequestContractError(f"invalid {name}")
    return model, max_prompt_tokens, max_completion_tokens


def canonical_request_contract(
    *,
    model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
) -> bytes:
    """Return deterministic content-free bytes committed by attestation/AAD."""
    model, prompt_limit, completion_limit = _validate_contract_values(
        model_id,
        max_prompt_tokens,
        max_completion_tokens,
    )
    document = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "model_id": model,
        "max_prompt_tokens": prompt_limit,
        "max_completion_tokens": completion_limit,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def request_contract_sha256(
    *,
    model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
) -> str:
    return hashlib.sha256(
        canonical_request_contract(
            model_id=model_id,
            max_prompt_tokens=max_prompt_tokens,
            max_completion_tokens=max_completion_tokens,
        )
    ).hexdigest()


def create_committed_attestation_nonce(
    *,
    model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
    entropy: bytes | None = None,
) -> str:
    """Create a fresh nonce that visibly and cryptographically commits the contract."""
    raw_entropy = entropy if entropy is not None else secrets.token_bytes(32)
    if not isinstance(raw_entropy, bytes) or len(raw_entropy) < MIN_NONCE_ENTROPY_BYTES:
        raise ConfidentialRequestContractError("insufficient attestation nonce entropy")
    digest = request_contract_sha256(
        model_id=model_id,
        max_prompt_tokens=max_prompt_tokens,
        max_completion_tokens=max_completion_tokens,
    )
    return f"{ATTESTATION_NONCE_PREFIX}:{digest}:{raw_entropy.hex()}"


def verify_committed_attestation_nonce(
    nonce: str,
    *,
    model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
) -> None:
    """Fail closed unless the attested nonce commits exactly the requested contract."""
    if not isinstance(nonce, str):
        raise ConfidentialRequestContractError("invalid committed attestation nonce")
    parts = nonce.split(":", 2)
    if len(parts) != 3 or parts[0] != ATTESTATION_NONCE_PREFIX:
        raise ConfidentialRequestContractError("attestation nonce lacks protected request commitment")
    digest, entropy_hex = parts[1], parts[2]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ConfidentialRequestContractError("invalid protected request contract digest")
    try:
        entropy = bytes.fromhex(entropy_hex)
    except ValueError as exc:
        raise ConfidentialRequestContractError("invalid committed attestation nonce entropy") from exc
    if len(entropy) < MIN_NONCE_ENTROPY_BYTES:
        raise ConfidentialRequestContractError("insufficient committed attestation nonce entropy")
    expected = request_contract_sha256(
        model_id=model_id,
        max_prompt_tokens=max_prompt_tokens,
        max_completion_tokens=max_completion_tokens,
    )
    if not hmac.compare_digest(digest, expected):
        raise ConfidentialRequestContractError("attestation nonce request contract mismatch")
