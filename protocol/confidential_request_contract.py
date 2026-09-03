"""Canonical commitments for confidential ComputeMesh attestation nonces.

`cmrc1` commits only the OpenAI model and token reservation and is retained for
compatibility. Production protected sessions use `cmrc2`, which contains both the
legacy request digest and a second digest over the complete content-free session
boundary. This lets existing OpenAI request-contract checks continue to verify the
model/budgets while the attestation verifier independently requires the stronger
session digest.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any


CONTRACT_SCHEMA_VERSION = 1
ATTESTATION_NONCE_PREFIX = "cmrc1"
SESSION_CONTRACT_SCHEMA_VERSION = 2
SESSION_ATTESTATION_NONCE_PREFIX = "cmrc2"
MAX_MODEL_ID_BYTES = 512
MAX_TOKEN_LIMIT = 1_000_000
MIN_NONCE_ENTROPY_BYTES = 16


class ConfidentialRequestContractError(ValueError):
    """Raised when a protected request/session commitment is invalid."""


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


def _bounded_text(name: str, value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise ConfidentialRequestContractError(f"invalid {name}")
    result = value.strip()
    if not result or len(result.encode("utf-8")) > limit:
        raise ConfidentialRequestContractError(f"invalid {name}")
    return result


def _sha256_label(name: str, value: Any) -> str:
    result = _bounded_text(name, value, 128)
    if not result.startswith("sha256:") or len(result) != 71:
        raise ConfidentialRequestContractError(f"invalid {name}")
    digest = result.removeprefix("sha256:")
    if any(ch not in "0123456789abcdef" for ch in digest):
        raise ConfidentialRequestContractError(f"invalid {name}")
    return result


def _privacy_class(value: Any) -> str:
    result = _bounded_text("privacy_class", value, 64)
    if result not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
        raise ConfidentialRequestContractError("invalid privacy_class")
    return result


def _operation(value: Any) -> str:
    result = _bounded_text("operation", value, 64)
    if result not in {"chat_completion", "ollama_chat", "ollama_generate"}:
        raise ConfidentialRequestContractError("invalid operation")
    return result


def canonical_request_contract(
    *,
    model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
) -> bytes:
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
    """Create the legacy `cmrc1` nonce for compatibility callers."""
    raw_entropy = entropy if entropy is not None else secrets.token_bytes(32)
    _validate_entropy(raw_entropy)
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
    """Verify the model/token portion of either a `cmrc1` or `cmrc2` nonce."""
    expected = request_contract_sha256(
        model_id=model_id,
        max_prompt_tokens=max_prompt_tokens,
        max_completion_tokens=max_completion_tokens,
    )
    if isinstance(nonce, str) and nonce.startswith(SESSION_ATTESTATION_NONCE_PREFIX + ":"):
        request_digest, _, _ = _parse_session_nonce(nonce)
        if not hmac.compare_digest(request_digest, expected):
            raise ConfidentialRequestContractError("attestation nonce request contract mismatch")
        return
    digest, _ = _parse_nonce(nonce, prefix=ATTESTATION_NONCE_PREFIX)
    if not hmac.compare_digest(digest, expected):
        raise ConfidentialRequestContractError("attestation nonce request contract mismatch")


def canonical_session_request_contract(
    *,
    account_id: str,
    job_id: str,
    model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
    node_id: str,
    runtime_digest: str,
    recipient_public_key: str,
    metering_public_key: str,
    data_plane_tls_sha256: str,
    privacy_class: str,
    operation: str,
) -> bytes:
    """Return the complete content-free production session commitment."""
    model, prompt_limit, completion_limit = _validate_contract_values(
        model_id,
        max_prompt_tokens,
        max_completion_tokens,
    )
    document = {
        "schema_version": SESSION_CONTRACT_SCHEMA_VERSION,
        "account_id": _bounded_text("account_id", account_id, 256),
        "job_id": _bounded_text("job_id", job_id, 256),
        "model_id": model,
        "max_prompt_tokens": prompt_limit,
        "max_completion_tokens": completion_limit,
        "node_id": _bounded_text("node_id", node_id, 256),
        "runtime_digest": _bounded_text("runtime_digest", runtime_digest, 512),
        "recipient_public_key": _bounded_text("recipient_public_key", recipient_public_key, 1024),
        "metering_public_key": _bounded_text("metering_public_key", metering_public_key, 1024),
        "data_plane_tls_sha256": _sha256_label("data_plane_tls_sha256", data_plane_tls_sha256),
        "privacy_class": _privacy_class(privacy_class),
        "operation": _operation(operation),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def session_request_contract_sha256(**values: Any) -> str:
    return hashlib.sha256(canonical_session_request_contract(**values)).hexdigest()


def create_committed_session_attestation_nonce(
    *,
    entropy: bytes | None = None,
    **values: Any,
) -> str:
    """Create a fresh `cmrc2` nonce committing the complete protected session."""
    raw_entropy = entropy if entropy is not None else secrets.token_bytes(32)
    _validate_entropy(raw_entropy)
    request_digest = request_contract_sha256(
        model_id=values.get("model_id"),
        max_prompt_tokens=values.get("max_prompt_tokens"),
        max_completion_tokens=values.get("max_completion_tokens"),
    )
    session_digest = session_request_contract_sha256(**values)
    return (
        f"{SESSION_ATTESTATION_NONCE_PREFIX}:{request_digest}:"
        f"{session_digest}:{raw_entropy.hex()}"
    )


def verify_committed_session_attestation_nonce(
    nonce: str,
    *,
    expected_entropy: bytes | None = None,
    **values: Any,
) -> None:
    """Require a vendor-attested nonce bound to the complete protected session."""
    request_digest, session_digest, entropy = _parse_session_nonce(nonce)
    expected_request = request_contract_sha256(
        model_id=values.get("model_id"),
        max_prompt_tokens=values.get("max_prompt_tokens"),
        max_completion_tokens=values.get("max_completion_tokens"),
    )
    if not hmac.compare_digest(request_digest, expected_request):
        raise ConfidentialRequestContractError("attestation nonce request contract mismatch")
    if expected_entropy is not None:
        _validate_entropy(expected_entropy)
        if not hmac.compare_digest(entropy, expected_entropy):
            raise ConfidentialRequestContractError("attestation nonce freshness challenge mismatch")
    expected_session = session_request_contract_sha256(**values)
    if not hmac.compare_digest(session_digest, expected_session):
        raise ConfidentialRequestContractError("attestation nonce session contract mismatch")


def _validate_entropy(value: Any) -> bytes:
    if not isinstance(value, bytes) or len(value) < MIN_NONCE_ENTROPY_BYTES:
        raise ConfidentialRequestContractError("insufficient attestation nonce entropy")
    return value


def _digest(value: str) -> str:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ConfidentialRequestContractError("invalid protected request contract digest")
    return value


def _parse_nonce(nonce: Any, *, prefix: str) -> tuple[str, bytes]:
    if not isinstance(nonce, str):
        raise ConfidentialRequestContractError("invalid committed attestation nonce")
    parts = nonce.split(":", 2)
    if len(parts) != 3 or parts[0] != prefix:
        raise ConfidentialRequestContractError("attestation nonce lacks protected request commitment")
    digest = _digest(parts[1])
    entropy = _entropy_hex(parts[2])
    return digest, entropy


def _parse_session_nonce(nonce: Any) -> tuple[str, str, bytes]:
    if not isinstance(nonce, str):
        raise ConfidentialRequestContractError("invalid committed attestation nonce")
    parts = nonce.split(":", 3)
    if len(parts) != 4 or parts[0] != SESSION_ATTESTATION_NONCE_PREFIX:
        raise ConfidentialRequestContractError("attestation nonce lacks protected session commitment")
    return _digest(parts[1]), _digest(parts[2]), _entropy_hex(parts[3])


def _entropy_hex(value: str) -> bytes:
    try:
        entropy = bytes.fromhex(value)
    except ValueError as exc:
        raise ConfidentialRequestContractError("invalid committed attestation nonce entropy") from exc
    _validate_entropy(entropy)
    return entropy
