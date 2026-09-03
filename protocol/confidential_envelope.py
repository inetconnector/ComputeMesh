"""Attestation-bound bidirectional encrypted envelopes for protected ComputeMesh jobs.

Protocol v2 cryptographically binds protected content to the authenticated account,
job, selected node, attestation nonce, approved runtime, attested data-plane TLS
identity, privacy class and operation.  The ordinary gateway can validate and
route these structures without possessing a content-decryption key or seeing
prompt/output plaintext.

Attestation verification, replay state, protected-runtime key custody and TEE
isolation are separate mandatory P0 controls.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import secrets
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services.common.secure_memory import secure_zero_memory


SCHEMA_VERSION = 2
REQUEST_ALGORITHM = "X25519-HKDF-SHA256-AES-256-GCM"
RESPONSE_ALGORITHM = "X25519-HKDF-SHA256-AES-256-GCM-RESPONSE"
REQUEST_KDF_INFO = b"ComputeMesh.ConfidentialEnvelope.request.v2"
RESPONSE_KDF_INFO = b"ComputeMesh.ConfidentialEnvelope.response.v2"
MAX_CIPHERTEXT_BYTES = 8 * 1024 * 1024
_ALLOWED_PRIVACY_CLASSES = frozenset({"CONFIDENTIAL", "CRYPTO_PRIVATE"})
_ALLOWED_OPERATIONS = frozenset({"chat_completion", "ollama_chat", "ollama_generate"})


class ConfidentialEnvelopeError(ValueError):
    """Raised when a protected envelope is malformed, misbound or unauthentic."""


@dataclass(frozen=True)
class ConfidentialBinding:
    """Security-critical values authenticated as request and response AAD."""

    account_id: str
    job_id: str
    node_id: str
    attestation_nonce: str
    runtime_digest: str
    data_plane_tls_sha256: str
    privacy_class: str
    operation: str

    def validate(self) -> None:
        for name, value, limit in (
            ("account_id", self.account_id, 256),
            ("job_id", self.job_id, 256),
            ("node_id", self.node_id, 256),
            ("attestation_nonce", self.attestation_nonce, 512),
            ("runtime_digest", self.runtime_digest, 512),
            ("data_plane_tls_sha256", self.data_plane_tls_sha256, 128),
            ("privacy_class", self.privacy_class, 64),
            ("operation", self.operation, 64),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ConfidentialEnvelopeError(f"invalid {name}")
        if self.privacy_class not in _ALLOWED_PRIVACY_CLASSES:
            raise ConfidentialEnvelopeError("invalid protected privacy_class")
        if self.operation not in _ALLOWED_OPERATIONS:
            raise ConfidentialEnvelopeError("invalid confidential operation")
        _validate_sha256_label(self.data_plane_tls_sha256, "data_plane_tls_sha256")

    def as_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "account_id": self.account_id,
            "job_id": self.job_id,
            "node_id": self.node_id,
            "attestation_nonce": self.attestation_nonce,
            "runtime_digest": self.runtime_digest,
            "data_plane_tls_sha256": self.data_plane_tls_sha256,
            "privacy_class": self.privacy_class,
            "operation": self.operation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfidentialBinding":
        if not isinstance(value, Mapping) or set(value) != {
            "account_id",
            "job_id",
            "node_id",
            "attestation_nonce",
            "runtime_digest",
            "data_plane_tls_sha256",
            "privacy_class",
            "operation",
        }:
            raise ConfidentialEnvelopeError("invalid envelope binding")
        binding = cls(
            account_id=value.get("account_id"),
            job_id=value.get("job_id"),
            node_id=value.get("node_id"),
            attestation_nonce=value.get("attestation_nonce"),
            runtime_digest=value.get("runtime_digest"),
            data_plane_tls_sha256=value.get("data_plane_tls_sha256"),
            privacy_class=value.get("privacy_class"),
            operation=value.get("operation"),
        )
        binding.validate()
        return binding


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
        if not isinstance(binding_value, Mapping):
            raise ConfidentialEnvelopeError("invalid envelope binding")
        envelope = cls(
            schema_version=value.get("schema_version"),
            algorithm=value.get("algorithm"),
            envelope_id=value.get("envelope_id"),
            binding=ConfidentialBinding.from_dict(binding_value),
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
        if self.algorithm != REQUEST_ALGORITHM:
            raise ConfidentialEnvelopeError("unsupported confidential envelope algorithm")
        _validate_hex_id(self.envelope_id, "envelope_id")
        self.binding.validate()
        _decode_b64url(self.sender_ephemeral_public_key, expected_len=32, label="sender key")
        _decode_b64url(self.salt, expected_len=32, label="salt")
        _decode_b64url(self.nonce, expected_len=12, label="nonce")
        ciphertext = _decode_b64url(self.ciphertext, label="ciphertext")
        if len(ciphertext) < 16 or len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            raise ConfidentialEnvelopeError("invalid ciphertext size")


@dataclass(frozen=True)
class ConfidentialResponseEnvelope:
    """TEE-to-client ciphertext bound to one exact request envelope."""

    schema_version: int
    algorithm: str
    response_id: str
    request_envelope_id: str
    binding: ConfidentialBinding
    nonce: str
    ciphertext: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "algorithm": self.algorithm,
            "response_id": self.response_id,
            "request_envelope_id": self.request_envelope_id,
            "binding": self.binding.as_dict(),
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfidentialResponseEnvelope":
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "algorithm",
            "response_id",
            "request_envelope_id",
            "binding",
            "nonce",
            "ciphertext",
        }:
            raise ConfidentialEnvelopeError("unexpected or missing confidential response fields")
        binding_value = value.get("binding")
        if not isinstance(binding_value, Mapping):
            raise ConfidentialEnvelopeError("invalid confidential response binding")
        response = cls(
            schema_version=value.get("schema_version"),
            algorithm=value.get("algorithm"),
            response_id=value.get("response_id"),
            request_envelope_id=value.get("request_envelope_id"),
            binding=ConfidentialBinding.from_dict(binding_value),
            nonce=value.get("nonce"),
            ciphertext=value.get("ciphertext"),
        )
        response.validate()
        return response

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ConfidentialEnvelopeError("unsupported confidential response version")
        if self.algorithm != RESPONSE_ALGORITHM:
            raise ConfidentialEnvelopeError("unsupported confidential response algorithm")
        _validate_hex_id(self.response_id, "response_id")
        _validate_hex_id(self.request_envelope_id, "request_envelope_id")
        self.binding.validate()
        _decode_b64url(self.nonce, expected_len=12, label="response nonce")
        ciphertext = _decode_b64url(self.ciphertext, label="response ciphertext")
        if len(ciphertext) < 16 or len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            raise ConfidentialEnvelopeError("invalid response ciphertext size")


@dataclass
class ConfidentialClientContext:
    """Zeroizable client-side state needed only to decrypt one protected response."""

    request_envelope_id: str
    binding: ConfidentialBinding
    _response_key: bytearray = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def response_key_view(self) -> memoryview:
        if self._closed:
            raise ConfidentialEnvelopeError("confidential client context is closed")
        return memoryview(self._response_key).toreadonly()

    def close(self) -> None:
        if not self._closed:
            secure_zero_memory(self._response_key)
            self._closed = True

    def __enter__(self) -> "ConfidentialClientContext":
        if self._closed:
            raise ConfidentialEnvelopeError("confidential client context is closed")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _validate_hex_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) != 32:
        raise ConfidentialEnvelopeError(f"invalid {label}")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ConfidentialEnvelopeError(f"invalid {label}") from exc


def _validate_sha256_label(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ConfidentialEnvelopeError(f"invalid {label}")
    digest = value.removeprefix("sha256:")
    if any(ch not in "0123456789abcdef" for ch in digest):
        raise ConfidentialEnvelopeError(f"invalid {label}")


def _b64url(value: bytes | bytearray | memoryview) -> str:
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


def _request_aad(*, envelope_id: str, binding: ConfidentialBinding) -> bytes:
    document = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": REQUEST_ALGORITHM,
        "envelope_id": envelope_id,
        "binding": binding.as_dict(),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _response_aad(
    *,
    response_id: str,
    request_envelope_id: str,
    binding: ConfidentialBinding,
) -> bytes:
    document = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": RESPONSE_ALGORITHM,
        "response_id": response_id,
        "request_envelope_id": request_envelope_id,
        "binding": binding.as_dict(),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _derive_key(*, shared_secret: bytes, salt: bytes, request_aad: bytes, info: bytes) -> bytearray:
    aad_digest = hashes.Hash(hashes.SHA256())
    aad_digest.update(request_aad)
    digest = aad_digest.finalize()
    return bytearray(
        HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=info + digest,
        ).derive(shared_secret)
    )


def _aes_gcm_encrypt(
    plaintext: bytes | bytearray | memoryview,
    *,
    key: bytearray,
    nonce: bytes,
    aad: bytes,
) -> bytes:
    encryptor = Cipher(algorithms.AES(memoryview(key)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    return ciphertext + encryptor.tag


def _aes_gcm_decrypt(
    ciphertext_and_tag: bytes,
    *,
    key: bytearray | memoryview,
    nonce: bytes,
    aad: bytes,
) -> bytearray:
    if len(ciphertext_and_tag) < 16:
        raise ConfidentialEnvelopeError("invalid authenticated ciphertext")
    ciphertext = ciphertext_and_tag[:-16]
    tag = ciphertext_and_tag[-16:]
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(aad)
    plaintext = bytearray(len(ciphertext) + 15)
    try:
        written = decryptor.update_into(ciphertext, plaintext)
        tail = decryptor.finalize()
    except InvalidTag as exc:
        secure_zero_memory(plaintext)
        raise ConfidentialEnvelopeError("confidential envelope authentication failed") from exc
    if tail:
        secure_zero_memory(plaintext)
        raise ConfidentialEnvelopeError("unexpected final plaintext allocation")
    del plaintext[written:]
    return plaintext


def generate_attested_recipient_keypair() -> tuple[X25519PrivateKey, str]:
    """Generate an ephemeral recipient key; private half must remain in the TEE."""
    private_key = X25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return private_key, _b64url(public_raw)


def create_confidential_request(
    plaintext: bytes | bytearray | memoryview,
    *,
    recipient_public_key: str,
    binding: ConfidentialBinding,
) -> tuple[ConfidentialEnvelope, ConfidentialClientContext]:
    """Encrypt a request and retain only a zeroizable response key for the client."""
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
    shared_secret = sender_private.exchange(recipient)
    salt = secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    envelope_id = secrets.token_hex(16)
    request_aad = _request_aad(envelope_id=envelope_id, binding=binding)
    request_key = _derive_key(
        shared_secret=shared_secret,
        salt=salt,
        request_aad=request_aad,
        info=REQUEST_KDF_INFO,
    )
    response_key = _derive_key(
        shared_secret=shared_secret,
        salt=salt,
        request_aad=request_aad,
        info=RESPONSE_KDF_INFO,
    )
    try:
        ciphertext = _aes_gcm_encrypt(plaintext, key=request_key, nonce=nonce, aad=request_aad)
    finally:
        secure_zero_memory(request_key)

    envelope = ConfidentialEnvelope(
        schema_version=SCHEMA_VERSION,
        algorithm=REQUEST_ALGORITHM,
        envelope_id=envelope_id,
        binding=binding,
        sender_ephemeral_public_key=_b64url(sender_public),
        salt=_b64url(salt),
        nonce=_b64url(nonce),
        ciphertext=_b64url(ciphertext),
    )
    envelope.validate()
    context = ConfidentialClientContext(
        request_envelope_id=envelope_id,
        binding=binding,
        _response_key=response_key,
    )
    return envelope, context


def encrypt_for_attested_recipient(
    plaintext: bytes | bytearray | memoryview,
    *,
    recipient_public_key: str,
    binding: ConfidentialBinding,
) -> ConfidentialEnvelope:
    """Compatibility helper for one-way callers that do not need a response key."""
    envelope, context = create_confidential_request(
        plaintext,
        recipient_public_key=recipient_public_key,
        binding=binding,
    )
    context.close()
    return envelope


def _derive_tee_keys(
    envelope: ConfidentialEnvelope,
    *,
    recipient_private_key: X25519PrivateKey,
) -> tuple[bytearray, bytearray]:
    sender_raw = _decode_b64url(
        envelope.sender_ephemeral_public_key,
        expected_len=32,
        label="sender key",
    )
    sender = X25519PublicKey.from_public_bytes(sender_raw)
    salt = _decode_b64url(envelope.salt, expected_len=32, label="salt")
    shared_secret = recipient_private_key.exchange(sender)
    request_aad = _request_aad(envelope_id=envelope.envelope_id, binding=envelope.binding)
    request_key = _derive_key(
        shared_secret=shared_secret,
        salt=salt,
        request_aad=request_aad,
        info=REQUEST_KDF_INFO,
    )
    response_key = _derive_key(
        shared_secret=shared_secret,
        salt=salt,
        request_aad=request_aad,
        info=RESPONSE_KDF_INFO,
    )
    return request_key, response_key


def decrypt_in_attested_recipient(
    envelope: ConfidentialEnvelope | Mapping[str, Any],
    *,
    recipient_private_key: X25519PrivateKey,
    expected_binding: ConfidentialBinding,
) -> bytearray:
    """Decrypt after attestation + replay checks; returns mutable zeroizable plaintext."""
    parsed = envelope if isinstance(envelope, ConfidentialEnvelope) else ConfidentialEnvelope.from_dict(envelope)
    parsed.validate()
    expected_binding.validate()
    if parsed.binding != expected_binding:
        raise ConfidentialEnvelopeError("confidential envelope binding mismatch")

    request_key, response_key = _derive_tee_keys(parsed, recipient_private_key=recipient_private_key)
    try:
        nonce = _decode_b64url(parsed.nonce, expected_len=12, label="nonce")
        ciphertext = _decode_b64url(parsed.ciphertext, label="ciphertext")
        aad = _request_aad(envelope_id=parsed.envelope_id, binding=parsed.binding)
        return _aes_gcm_decrypt(ciphertext, key=request_key, nonce=nonce, aad=aad)
    finally:
        secure_zero_memory(request_key)
        secure_zero_memory(response_key)


def encrypt_response_in_attested_recipient(
    request_envelope: ConfidentialEnvelope | Mapping[str, Any],
    plaintext: bytes | bytearray | memoryview,
    *,
    recipient_private_key: X25519PrivateKey,
) -> ConfidentialResponseEnvelope:
    """Encrypt TEE output so the gateway can return it without seeing plaintext."""
    parsed = (
        request_envelope
        if isinstance(request_envelope, ConfidentialEnvelope)
        else ConfidentialEnvelope.from_dict(request_envelope)
    )
    parsed.validate()
    if not isinstance(plaintext, (bytes, bytearray, memoryview)):
        raise TypeError("plaintext must be bytes-like")
    if len(plaintext) > MAX_CIPHERTEXT_BYTES - 16:
        raise ConfidentialEnvelopeError("response plaintext exceeds confidential envelope limit")

    request_key, response_key = _derive_tee_keys(parsed, recipient_private_key=recipient_private_key)
    response_id = secrets.token_hex(16)
    nonce = secrets.token_bytes(12)
    aad = _response_aad(
        response_id=response_id,
        request_envelope_id=parsed.envelope_id,
        binding=parsed.binding,
    )
    try:
        ciphertext = _aes_gcm_encrypt(plaintext, key=response_key, nonce=nonce, aad=aad)
    finally:
        secure_zero_memory(request_key)
        secure_zero_memory(response_key)
    response = ConfidentialResponseEnvelope(
        schema_version=SCHEMA_VERSION,
        algorithm=RESPONSE_ALGORITHM,
        response_id=response_id,
        request_envelope_id=parsed.envelope_id,
        binding=parsed.binding,
        nonce=_b64url(nonce),
        ciphertext=_b64url(ciphertext),
    )
    response.validate()
    return response


def decrypt_confidential_response(
    response: ConfidentialResponseEnvelope | Mapping[str, Any],
    *,
    client_context: ConfidentialClientContext,
) -> bytearray:
    """Decrypt one TEE response using the request-scoped zeroizable client key."""
    parsed = (
        response
        if isinstance(response, ConfidentialResponseEnvelope)
        else ConfidentialResponseEnvelope.from_dict(response)
    )
    parsed.validate()
    if parsed.request_envelope_id != client_context.request_envelope_id:
        raise ConfidentialEnvelopeError("confidential response request binding mismatch")
    if parsed.binding != client_context.binding:
        raise ConfidentialEnvelopeError("confidential response binding mismatch")
    nonce = _decode_b64url(parsed.nonce, expected_len=12, label="response nonce")
    ciphertext = _decode_b64url(parsed.ciphertext, label="response ciphertext")
    aad = _response_aad(
        response_id=parsed.response_id,
        request_envelope_id=parsed.request_envelope_id,
        binding=parsed.binding,
    )
    key_view = client_context.response_key_view()
    try:
        return _aes_gcm_decrypt(ciphertext, key=key_view, nonce=nonce, aad=aad)
    finally:
        key_view.release()
