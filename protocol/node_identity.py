from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import binascii
import hashlib
import json
import struct
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .node_session import (
    AuthenticationAttempt,
    AuthenticationDecision,
    NodeHelloInfo,
)

AUTH_METHOD = "computemesh-ed25519-v1"
PROOF_VERSION = 1
DEFAULT_PROOF_TTL = timedelta(seconds=30)
MAX_PROOF_TTL = timedelta(seconds=60)
DEFAULT_CLOCK_SKEW = timedelta(seconds=30)
DEFAULT_SESSION_LIFETIME = timedelta(minutes=15)
_DOMAIN = b"ComputeMesh.NodeAuth.v1\x00"
_REQUIRED_PROOF_FIELDS = {
    "v",
    "node_id",
    "key_id",
    "issued_at",
    "expires_at",
    "signature",
}


class NodeIdentityError(ValueError):
    pass


class NodeProofMalformed(NodeIdentityError):
    pass


@dataclass(frozen=True)
class VerificationKey:
    node_id: str
    principal_id: str
    key_id: str
    public_key: bytes
    active: bool = True

    def __post_init__(self) -> None:
        if not (1 <= len(self.node_id) <= 128):
            raise ValueError("invalid node_id")
        if not (1 <= len(self.principal_id) <= 256):
            raise ValueError("invalid principal_id")
        if not (1 <= len(self.key_id) <= 128):
            raise ValueError("invalid key_id")
        if len(self.public_key) != 32:
            raise ValueError("Ed25519 public keys must be 32 bytes")


class VerificationKeyResolver(Protocol):
    def resolve_key(self, node_id: str, key_id: str) -> VerificationKey: ...


@dataclass(frozen=True)
class NodeAuthProof:
    node_id: str
    key_id: str
    issued_at: int
    expires_at: int
    signature: bytes
    version: int = PROOF_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version != PROOF_VERSION:
            raise NodeProofMalformed("unsupported node proof version")
        if not isinstance(self.node_id, str) or not (1 <= len(self.node_id) <= 128):
            raise NodeProofMalformed("invalid proof node_id")
        if not isinstance(self.key_id, str) or not (1 <= len(self.key_id) <= 128):
            raise NodeProofMalformed("invalid proof key_id")
        if isinstance(self.issued_at, bool) or not isinstance(self.issued_at, int):
            raise NodeProofMalformed("issued_at must be integer epoch seconds")
        if isinstance(self.expires_at, bool) or not isinstance(self.expires_at, int):
            raise NodeProofMalformed("expires_at must be integer epoch seconds")
        if self.expires_at <= self.issued_at:
            raise NodeProofMalformed("proof expires_at must be later than issued_at")
        if len(self.signature) != 64:
            raise NodeProofMalformed("Ed25519 signature must be 64 bytes")

    def encode(self) -> str:
        document = {
            "v": self.version,
            "node_id": self.node_id,
            "key_id": self.key_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": _b64u(self.signature),
        }
        raw = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        return _b64u(raw)

    @classmethod
    def decode(cls, credential: str) -> "NodeAuthProof":
        if not isinstance(credential, str) or not (1 <= len(credential) <= 4096):
            raise NodeProofMalformed("credential must be a bounded string")
        try:
            raw = _b64u_decode(credential, max_bytes=3072)
            document = json.loads(raw.decode("ascii"))
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise NodeProofMalformed("credential is not a valid v1 proof") from exc
        if not isinstance(document, dict) or set(document) != _REQUIRED_PROOF_FIELDS:
            raise NodeProofMalformed("credential has unknown or missing proof fields")
        try:
            signature = _b64u_decode(document["signature"], max_bytes=64)
        except (TypeError, ValueError) as exc:
            raise NodeProofMalformed("invalid proof signature encoding") from exc
        return cls(
            version=document["v"],
            node_id=document["node_id"],
            key_id=document["key_id"],
            issued_at=document["issued_at"],
            expires_at=document["expires_at"],
            signature=signature,
        )


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str, *, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("base64url value must be non-empty")
    if len(value) > ((max_bytes + 2) // 3) * 4 + 4:
        raise ValueError("base64url value is too large")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError("invalid base64url characters")
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64url encoding") from exc
    if len(decoded) > max_bytes:
        raise ValueError("decoded value is too large")
    return decoded


def _pack(value: str) -> bytes:
    encoded = value.encode("utf-8")
    if len(encoded) > 65535:
        raise ValueError("signed field is too large")
    return struct.pack(">H", len(encoded)) + encoded


def _hello_digest(hello: NodeHelloInfo) -> bytes:
    document = {
        "protocol_major": hello.protocol_major,
        "protocol_minor": hello.protocol_minor,
        "agent_version": hello.agent_version,
        "platform": hello.platform,
        "node_id": hello.node_id,
        "supported_auth_methods": sorted(hello.supported_auth_methods),
        "capabilities": sorted(hello.capabilities),
    }
    raw = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).digest()


def signing_message(
    *,
    session_id: str,
    challenge: str,
    hello: NodeHelloInfo,
    node_id: str,
    key_id: str,
    issued_at: int,
    expires_at: int,
) -> bytes:
    if isinstance(issued_at, bool) or not isinstance(issued_at, int):
        raise ValueError("issued_at must be integer epoch seconds")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        raise ValueError("expires_at must be integer epoch seconds")
    return b"".join(
        (
            _DOMAIN,
            _pack(session_id),
            _pack(challenge),
            _pack(node_id),
            _pack(key_id),
            struct.pack(">IIqq", hello.protocol_major, hello.protocol_minor, issued_at, expires_at),
            _hello_digest(hello),
        )
    )


def key_id_from_public_key(public_key: bytes) -> str:
    if len(public_key) != 32:
        raise ValueError("Ed25519 public keys must be 32 bytes")
    return "ed25519:" + _b64u(hashlib.sha256(public_key).digest())


def create_node_auth_proof(
    *,
    private_key: Ed25519PrivateKey,
    node_id: str,
    key_id: str,
    session_id: str,
    challenge: str,
    hello: NodeHelloInfo,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_PROOF_TTL,
) -> str:
    if ttl <= timedelta(0) or ttl > MAX_PROOF_TTL:
        raise ValueError("proof ttl must be positive and <= 60 seconds")
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued_at = int(now_utc.timestamp())
    expires_at = int((now_utc + ttl).timestamp())
    message = signing_message(
        session_id=session_id,
        challenge=challenge,
        hello=hello,
        node_id=node_id,
        key_id=key_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return NodeAuthProof(
        node_id=node_id,
        key_id=key_id,
        issued_at=issued_at,
        expires_at=expires_at,
        signature=private_key.sign(message),
    ).encode()


class Ed25519ChallengeVerifier:
    """Reference M1 verifier for enrolled Ed25519 node keys.

    This verifies a short-lived challenge proof and returns a bounded authenticated
    session lease. Transport security and enrollment authorization remain separate.
    """

    def __init__(
        self,
        resolver: VerificationKeyResolver,
        *,
        clock_skew: timedelta = DEFAULT_CLOCK_SKEW,
        max_proof_ttl: timedelta = MAX_PROOF_TTL,
        session_lifetime: timedelta = DEFAULT_SESSION_LIFETIME,
    ):
        if clock_skew < timedelta(0):
            raise ValueError("clock_skew must be non-negative")
        if max_proof_ttl <= timedelta(0):
            raise ValueError("max_proof_ttl must be positive")
        if session_lifetime <= timedelta(0):
            raise ValueError("session_lifetime must be positive")
        self.resolver = resolver
        self.clock_skew = clock_skew
        self.max_proof_ttl = max_proof_ttl
        self.session_lifetime = session_lifetime

    def _deny(self, reason: str) -> AuthenticationDecision:
        return AuthenticationDecision(authenticated=False, reason=reason)

    def verify(
        self,
        *,
        session_id: str,
        challenge: str,
        hello: NodeHelloInfo,
        attempt: AuthenticationAttempt,
        now: datetime,
    ) -> AuthenticationDecision:
        if attempt.method != AUTH_METHOD:
            return self._deny("unsupported authentication method")
        try:
            proof = NodeAuthProof.decode(attempt.credential)
        except NodeIdentityError:
            return self._deny("malformed node proof")

        now_utc = now.astimezone(timezone.utc)
        issued = datetime.fromtimestamp(proof.issued_at, tz=timezone.utc)
        expires = datetime.fromtimestamp(proof.expires_at, tz=timezone.utc)
        if expires - issued > self.max_proof_ttl:
            return self._deny("node proof ttl exceeds policy")
        if issued > now_utc + self.clock_skew:
            return self._deny("node proof issued_at is too far in the future")
        if expires <= now_utc:
            return self._deny("node proof has expired")
        if hello.node_id is not None and proof.node_id != hello.node_id:
            return self._deny("node proof identity does not match NodeHello")

        try:
            record = self.resolver.resolve_key(proof.node_id, proof.key_id)
        except KeyError:
            return self._deny("unknown or unavailable node key")
        if not record.active:
            return self._deny("node key is revoked or disabled")
        if record.node_id != proof.node_id or record.key_id != proof.key_id:
            return self._deny("resolved node key does not match proof")
        if key_id_from_public_key(record.public_key) != record.key_id:
            return self._deny("node key fingerprint is inconsistent")

        message = signing_message(
            session_id=session_id,
            challenge=challenge,
            hello=hello,
            node_id=proof.node_id,
            key_id=proof.key_id,
            issued_at=proof.issued_at,
            expires_at=proof.expires_at,
        )
        try:
            Ed25519PublicKey.from_public_bytes(record.public_key).verify(
                proof.signature, message
            )
        except (InvalidSignature, ValueError):
            return self._deny("invalid node signature")

        return AuthenticationDecision(
            authenticated=True,
            node_id=record.node_id,
            principal_id=record.principal_id,
            credential_expires_at=now_utc + self.session_lifetime,
            key_id=record.key_id,
        )
