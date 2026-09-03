"""Content-free, attestation-keyed metering receipts for confidential inference.

The protected runtime signs only billing/evidence metadata. Prompt text, output
text, token IDs and activations are forbidden from this structure. The signing
Ed25519 public key must itself be bound into the verified confidential attestation.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import secrets
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


RECEIPT_SCHEMA_VERSION = 1
MAX_TOKENS_PER_SIDE = 10_000_000


class ConfidentialMeteringError(ValueError):
    pass


@dataclass(frozen=True)
class ConfidentialUsageReceipt:
    schema_version: int
    receipt_id: str
    account_id: str
    job_id: str
    request_envelope_id: str
    response_id: str
    node_id: str
    runtime_digest: str
    privacy_class: str
    operation: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    finished_at: str
    signature: str

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "account_id": self.account_id,
            "job_id": self.job_id,
            "request_envelope_id": self.request_envelope_id,
            "response_id": self.response_id,
            "node_id": self.node_id,
            "runtime_digest": self.runtime_digest,
            "privacy_class": self.privacy_class,
            "operation": self.operation,
            "model_id": self.model_id,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "finished_at": self.finished_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature": self.signature}

    def validate(self) -> None:
        if self.schema_version != RECEIPT_SCHEMA_VERSION:
            raise ConfidentialMeteringError("unsupported confidential metering receipt version")
        _validate_hex_id(self.receipt_id, "receipt_id")
        _validate_hex_id(self.request_envelope_id, "request_envelope_id")
        _validate_hex_id(self.response_id, "response_id")
        for name, value, limit in (
            ("account_id", self.account_id, 256),
            ("job_id", self.job_id, 256),
            ("node_id", self.node_id, 256),
            ("runtime_digest", self.runtime_digest, 512),
            ("privacy_class", self.privacy_class, 64),
            ("operation", self.operation, 64),
            ("model_id", self.model_id, 512),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ConfidentialMeteringError(f"invalid {name}")
        if self.privacy_class not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
            raise ConfidentialMeteringError("invalid confidential metering privacy class")
        if self.operation not in {"chat_completion", "ollama_chat", "ollama_generate"}:
            raise ConfidentialMeteringError("invalid confidential metering operation")
        for name, value in (
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > MAX_TOKENS_PER_SIDE:
                raise ConfidentialMeteringError(f"invalid {name}")
        _parse_timestamp(self.finished_at)
        _decode_b64(self.signature, expected_len=64, label="metering signature")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfidentialUsageReceipt":
        expected = {
            "schema_version",
            "receipt_id",
            "account_id",
            "job_id",
            "request_envelope_id",
            "response_id",
            "node_id",
            "runtime_digest",
            "privacy_class",
            "operation",
            "model_id",
            "prompt_tokens",
            "completion_tokens",
            "finished_at",
            "signature",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ConfidentialMeteringError("invalid confidential metering receipt contract")
        receipt = cls(**{name: value.get(name) for name in expected})
        receipt.validate()
        return receipt


def generate_attested_metering_keypair() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return private_key, _b64(public_raw)


def sign_confidential_usage(
    *,
    private_key: Ed25519PrivateKey,
    account_id: str,
    job_id: str,
    request_envelope_id: str,
    response_id: str,
    node_id: str,
    runtime_digest: str,
    privacy_class: str,
    operation: str,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    finished_at: datetime | None = None,
) -> ConfidentialUsageReceipt:
    instant = finished_at or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ConfidentialMeteringError("metering timestamp must be timezone-aware")
    unsigned = ConfidentialUsageReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        receipt_id=secrets.token_hex(16),
        account_id=account_id,
        job_id=job_id,
        request_envelope_id=request_envelope_id,
        response_id=response_id,
        node_id=node_id,
        runtime_digest=runtime_digest,
        privacy_class=privacy_class,
        operation=operation,
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        finished_at=instant.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        signature=_b64(b"\x00" * 64),
    )
    unsigned.validate()
    signature = private_key.sign(_canonical(unsigned.unsigned_dict()))
    receipt = ConfidentialUsageReceipt(**{**unsigned.__dict__, "signature": _b64(signature)})
    receipt.validate()
    return receipt


def verify_confidential_usage_receipt(
    receipt: ConfidentialUsageReceipt | Mapping[str, Any],
    *,
    attested_metering_public_key: str,
    expected_account_id: str,
    expected_job_id: str,
    expected_request_envelope_id: str,
    expected_response_id: str,
    expected_node_id: str,
    expected_runtime_digest: str,
    expected_privacy_class: str,
    expected_operation: str,
    expected_model_id: str,
    max_prompt_tokens: int,
    max_completion_tokens: int,
    not_after: datetime | None = None,
) -> ConfidentialUsageReceipt:
    parsed = receipt if isinstance(receipt, ConfidentialUsageReceipt) else ConfidentialUsageReceipt.from_dict(receipt)
    parsed.validate()
    expected = {
        "account_id": expected_account_id,
        "job_id": expected_job_id,
        "request_envelope_id": expected_request_envelope_id,
        "response_id": expected_response_id,
        "node_id": expected_node_id,
        "runtime_digest": expected_runtime_digest,
        "privacy_class": expected_privacy_class,
        "operation": expected_operation,
        "model_id": expected_model_id,
    }
    for name, value in expected.items():
        if getattr(parsed, name) != value:
            raise ConfidentialMeteringError(f"confidential metering {name} binding mismatch")
    if parsed.prompt_tokens > max_prompt_tokens:
        raise ConfidentialMeteringError("confidential prompt token count exceeds reserved maximum")
    if parsed.completion_tokens > max_completion_tokens:
        raise ConfidentialMeteringError("confidential completion token count exceeds reserved maximum")
    finished = _parse_timestamp(parsed.finished_at)
    if not_after is not None:
        if not_after.tzinfo is None or not_after.utcoffset() is None:
            raise ConfidentialMeteringError("receipt not_after must be timezone-aware")
        if finished > not_after.astimezone(UTC):
            raise ConfidentialMeteringError("confidential metering receipt exceeds session lifetime")
    public_raw = _decode_b64(attested_metering_public_key, expected_len=32, label="attested metering key")
    signature = _decode_b64(parsed.signature, expected_len=64, label="metering signature")
    try:
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, _canonical(parsed.unsigned_dict()))
    except (ValueError, InvalidSignature) as exc:
        raise ConfidentialMeteringError("confidential metering signature verification failed") from exc
    return parsed


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_b64(value: Any, *, expected_len: int, label: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ConfidentialMeteringError(f"invalid {label}")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, UnicodeError) as exc:
        raise ConfidentialMeteringError(f"invalid {label}") from exc
    if len(raw) != expected_len:
        raise ConfidentialMeteringError(f"invalid {label} length")
    return raw


def _validate_hex_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) != 32:
        raise ConfidentialMeteringError(f"invalid {label}")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ConfidentialMeteringError(f"invalid {label}") from exc


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ConfidentialMeteringError("invalid metering timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfidentialMeteringError("invalid metering timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConfidentialMeteringError("metering timestamp must be timezone-aware")
    return parsed.astimezone(UTC)
