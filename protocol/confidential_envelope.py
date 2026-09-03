"""Attestation-bound encrypted payload envelope for protected ComputeMesh jobs.

The ordinary gateway may route this structure without holding the plaintext or a
content-decryption key.  The recipient key is expected to be an ephemeral X25519
public key whose identity was bound into a verified confidential attestation.

This module provides cryptographic framing only.  Attestation verification,
key-release policy, replay state and TEE isolation remain separate mandatory P0
controls and must all pass before a protected request is considered confidential.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import secrets
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


SCHEMA_VERSION = 1
ALGORITHM = "X25519-HKDF-SHA256-AES-256-GCM"
KDF_INFO = b"ComputeMesh.ConfidentialEnvelope.v1"
MAX_CIPHERTEXT_BYTES = 8 * 1024 * 1024


class ConfidentialEnvelopeError(ValueError):
    """Raised when a protected envelope is malformed, misbound or unauthentic."""


@dataclass(frozen=True)
class ConfidentialBinding:
    """Security-critical values cryptographically authenticated as AES-GCM AAD."""

    job_id: str
    node_id: str
    attestation_nonce: str
    runtime_digest: str

    def validate(self) -> None:
        for name, value, limit in (
            ("job_id", self.job_id, 256),
            ("node_id", self.node_id, 256),
            ("attestation_nonce", self.attestation_nonce, 512),
            ("runtime_digest", self.runtime_digest, 512),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ConfidentialEnvelopeError(f"invalid {name}")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "job_id": self.job_id,
            "node_id": self.node_id,
            "attestation_nonce": self.attestation_nonce,
            "runtime_digest": self.runtime_digest,
        }


@dataclass(frozen=True)
class ConfidentialEnvelope:
    schema_version: int
    algorithm: str
    envelope_id: str
    binding: ConfidentialBinding
    sender_ephemeral_public_key: str
    salt: str
    nonce: str
    ciphertext: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "algorithm": self.algorithm,
            "envelope_id": self.envelope_id,
            "binding": self.binding.as_dict(),
            "sender_ephemeral_public_key": self.sender_ephemeral_public_key,
            "salt": self.salt,
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfidentialEnvelope":
        if not isinstance(value, Mapping):
            raise ConfidentialEnvelopeError("envelope must be an object")
        required = {
            "schema_version",
            "algorithm",
            "envelope_id",
            "binding",
            "sender_ephemeral_public_key",
            "salt",
            "nonce",
            "ciphertext",
        }
        if set(value) != required:
            raise ConfidentialEnvelopeError("unexpected or missing envelope fields")
        binding_value = value.get("binding")
        if not isinstance(binding_value, Mapping) or set(binding_value) != {
            "job_id",
            "node_id",
            "attestation_nonce",
            "runtime_digest",
        }:
            raise ConfidentialEnvelopeError("invalid envelope binding")
        binding = ConfidentialBinding(
            job_id=str(binding_value["job_id"]),
            node_id=str(binding_value["node_id"]),
            attestation_nonce=str(binding_value["attestation_nonce"]),
            runtime_digest=str(binding_value["runtime_digest"]),
        )
        binding.validate()
        envelope = cls(
            schema_version=value.get("schema_version"),
            algorithm=value.get("algorithm"),
            envelope_id=value.get("envelope_id"),
            binding=binding,
            sender_ephemeral_public_key=value.get("sender_ephemeral_public_key"),
            salt=value.get("salt"),
            nonce=value.get("nonce"),
            ciphertext=value.get("ciphertext"),
        )
        envelope.validate()
        return envelope

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ConfidentialEnvelopeError("unsupported confidential envelope version")
        if self.algorithm != ALGORITHM:
            raise ConfidentialEnvelopeError("unsupported confidential envelope algorithm")
        if not isinstance(self.envelope_id, str) or len(self.envelope_id) != 32:
            raise ConfidentialEnvelopeError("invalid envelope_id")
        try:
            bytes.fromhex(self.envelope_id)
        except ValueError as exc:
            raise ConfidentialEnvelopeError("invalid envelope_id") from exc
        self.binding.validate()
        _decode_b64url(self.sender_ephemeral_public_key, expected_len=32, label="sender key")
        _decode_b64url(self.salt, expected_len=32, label="salt")
        _decode_b64url(self.nonce, expected_len=12, label="nonce")
        ciphertext = _decode_b64url(self.ciphertext, label="ciphertext")
        if len(ciphertext) < 16 or len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            raise ConfidentialEnvelopeError("invalid ciphertext size")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_b64url(value: Any, *, expected_len: int | None = None, label: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > MAX_CIPHERTEXT_BYTES * 2:
        raise ConfidentialEnvelopeError(f"invalid {label}")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, UnicodeError) as exc:
        raise ConfidentialEnvelopeError(f"invalid {label}") from exc
    if expected_len is not None and len(raw) != expected_len:
        raise ConfidentialEnvelopeError(f"invalid {label} length")
    return raw


def _aad(*, envelope_id: str, binding: ConfidentialBinding) -> bytes:
    document = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "envelope_id": envelope_id,
        "binding": binding.as_dict(),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _derive_key(
    *,
    private_key: X25519PrivateKey,
    peer_public_key: X25519PublicKey,
    salt: bytes,
    aad: bytes,
) -> bytes:
    shared_secret = private_key.exchange(peer_public_key)
    # The KDF context includes the authenticated binding digest so a derived key
    # is scoped to one exact protected request even before AES-GCM AAD checking.
    aad_digest = hashes.Hash(hashes.SHA256())
    aad_digest.update(aad)
    digest = aad_digest.finalize()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=KDF_INFO + digest,
    ).derive(shared_secret)


def generate_attested_recipient_keypair() -> tuple[X25519PrivateKey, str]:
    """Generate a request/session recipient key; private half must remain in the TEE."""
    private_key = X25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return private_key, _b64url(public_raw)


def encrypt_for_attested_recipient(
    plaintext: bytes | bytearray | memoryview,
    *,
    recipient_public_key: str,
    binding: ConfidentialBinding,
) -> ConfidentialEnvelope:
    """Encrypt content to the ephemeral public key carried by the attestation."""
    if not isinstance(plaintext, (bytes, bytearray, memoryview)):
        raise TypeError("plaintext must be bytes-like")
    if len(plaintext) > MAX_CIPHERTEXT_BYTES - 16:
        raise ConfidentialEnvelopeError("plaintext exceeds confidential envelope limit")
    binding.validate()
    recipient_raw = _decode_b64url(recipient_public_key, expected_len=32, label="recipient key")
    try:
        recipient = X25519PublicKey.from_public_bytes(recipient_raw)
    except ValueError as exc:
        raise ConfidentialEnvelopeError("invalid recipient X25519 key") from exc

    sender_private = X25519PrivateKey.generate()
    sender_public = sender_private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    salt = secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    envelope_id = secrets.token_hex(16)
    aad = _aad(envelope_id=envelope_id, binding=binding)
    content_key = _derive_key(
        private_key=sender_private,
        peer_public_key=recipient,
        salt=salt,
        aad=aad,
    )
    ciphertext = AESGCM(content_key).encrypt(nonce, plaintext, aad)
    envelope = ConfidentialEnvelope(
        schema_version=SCHEMA_VERSION,
        algorithm=ALGORITHM,
        envelope_id=envelope_id,
        binding=binding,
        sender_ephemeral_public_key=_b64url(sender_public),
        salt=_b64url(salt),
        nonce=_b64url(nonce),
        ciphertext=_b64url(ciphertext),
    )
    envelope.validate()
    return envelope


def decrypt_in_attested_recipient(
    envelope: ConfidentialEnvelope | Mapping[str, Any],
    *,
    recipient_private_key: X25519PrivateKey,
    expected_binding: ConfidentialBinding,
) -> bytearray:
    """Decrypt only after the caller has verified attestation and replay policy.

    Returns a mutable bytearray so the protected runtime can page-lock it and
    explicitly zeroize it after parsing/consumption.
    """
    parsed = envelope if isinstance(envelope, ConfidentialEnvelope) else ConfidentialEnvelope.from_dict(envelope)
    parsed.validate()
    expected_binding.validate()
    if parsed.binding != expected_binding:
        raise ConfidentialEnvelopeError("confidential envelope binding mismatch")

    sender_raw = _decode_b64url(
        parsed.sender_ephemeral_public_key,
        expected_len=32,
        label="sender key",
    )
    sender = X25519PublicKey.from_public_bytes(sender_raw)
    salt = _decode_b64url(parsed.salt, expected_len=32, label="salt")
    nonce = _decode_b64url(parsed.nonce, expected_len=12, label="nonce")
    ciphertext = _decode_b64url(parsed.ciphertext, label="ciphertext")
    aad = _aad(envelope_id=parsed.envelope_id, binding=parsed.binding)
    content_key = _derive_key(
        private_key=recipient_private_key,
        peer_public_key=sender,
        salt=salt,
        aad=aad,
    )
    try:
        plaintext = AESGCM(content_key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise ConfidentialEnvelopeError("confidential envelope authentication failed") from exc
    return bytearray(plaintext)
