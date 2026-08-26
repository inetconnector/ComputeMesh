"""Ed25519 participant attestations for verified ComputeMesh execution settlement."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from protocol.node_identity import VerificationKey, key_id_from_public_key

DOMAIN = b"ComputeMesh.ExecutionAttestation.v1\x00"
MAX_ATTESTATION_BYTES = 1024 * 1024
DEFAULT_CLOCK_SKEW = timedelta(seconds=30)
MAX_TTL = timedelta(minutes=5)


class ExecutionAttestationError(ValueError):
    pass


class VerificationKeyResolver(Protocol):
    def resolve_key(self, node_id: str, key_id: str) -> VerificationKey: ...


@dataclass(frozen=True)
class AttestationClaims:
    node_id: str
    key_id: str
    job_id: str
    placement_decision_id: str
    model_sha256: str
    runtime_sha256: str
    evidence_sha256: str
    output_sha256: str
    issued_at: int
    expires_at: int


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ExecutionAttestationError("invalid signature encoding")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ExecutionAttestationError("invalid signature encoding")
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:
        raise ExecutionAttestationError("invalid signature encoding") from exc
    if len(raw) != 64:
        raise ExecutionAttestationError("Ed25519 signature must be 64 bytes")
    return raw


def _validate_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ExecutionAttestationError(f"{label} must be a lowercase SHA-256 digest")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise ExecutionAttestationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _claims_document(claims: AttestationClaims) -> dict[str, Any]:
    return {
        "v": 1,
        "node_id": claims.node_id,
        "key_id": claims.key_id,
        "job_id": claims.job_id,
        "placement_decision_id": claims.placement_decision_id,
        "model_sha256": claims.model_sha256,
        "runtime_sha256": claims.runtime_sha256,
        "evidence_sha256": claims.evidence_sha256,
        "output_sha256": claims.output_sha256,
        "issued_at": claims.issued_at,
        "expires_at": claims.expires_at,
    }


def signing_message(claims: AttestationClaims) -> bytes:
    if not (1 <= len(claims.node_id) <= 128 and 1 <= len(claims.key_id) <= 128):
        raise ExecutionAttestationError("invalid node/key identity")
    if not (1 <= len(claims.job_id) <= 256 and 1 <= len(claims.placement_decision_id) <= 128):
        raise ExecutionAttestationError("invalid job/placement identity")
    _validate_sha256(claims.model_sha256, "model_sha256")
    _validate_sha256(claims.runtime_sha256, "runtime_sha256")
    _validate_sha256(claims.evidence_sha256, "evidence_sha256")
    _validate_sha256(claims.output_sha256, "output_sha256")
    if claims.expires_at <= claims.issued_at:
        raise ExecutionAttestationError("attestation expiry must follow issued_at")
    raw = json.dumps(_claims_document(claims), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return DOMAIN + raw


def create_execution_attestation(*, private_key: Ed25519PrivateKey, claims: AttestationClaims) -> dict[str, Any]:
    document = _claims_document(claims)
    document["signature"] = _b64u(private_key.sign(signing_message(claims)))
    return document


def runtime_digest(runtime: dict[str, Any]) -> str:
    raw = json.dumps(runtime, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_attestation(value: Any) -> tuple[AttestationClaims, bytes]:
    if not isinstance(value, dict):
        raise ExecutionAttestationError("attestation must be an object")
    expected = {
        "v", "node_id", "key_id", "job_id", "placement_decision_id", "model_sha256",
        "runtime_sha256", "evidence_sha256", "output_sha256", "issued_at", "expires_at", "signature",
    }
    if set(value) != expected or value.get("v") != 1:
        raise ExecutionAttestationError("attestation has unknown/missing fields or version")
    try:
        claims = AttestationClaims(
            node_id=str(value["node_id"]), key_id=str(value["key_id"]), job_id=str(value["job_id"]),
            placement_decision_id=str(value["placement_decision_id"]), model_sha256=str(value["model_sha256"]),
            runtime_sha256=str(value["runtime_sha256"]), evidence_sha256=str(value["evidence_sha256"]),
            output_sha256=str(value["output_sha256"]), issued_at=int(value["issued_at"]), expires_at=int(value["expires_at"]),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionAttestationError("attestation claims are malformed") from exc
    if isinstance(value["issued_at"], bool) or isinstance(value["expires_at"], bool):
        raise ExecutionAttestationError("attestation timestamps must be integer epoch seconds")
    return claims, _b64u_decode(value["signature"])


def verify_execution_attestations(
    path: str | Path,
    *,
    resolver: VerificationKeyResolver,
    expected_nodes: tuple[str, ...],
    job_id: str,
    placement_decision_id: str,
    model_sha256: str,
    runtime_sha256: str,
    evidence_sha256: str,
    output_sha256: str,
    now: datetime | None = None,
    clock_skew: timedelta = DEFAULT_CLOCK_SKEW,
) -> tuple[str, ...]:
    p = Path(path)
    if p.is_symlink() or not p.is_file() or not (0 < p.stat().st_size <= MAX_ATTESTATION_BYTES):
        raise ExecutionAttestationError("attestation bundle must be a bounded regular file")
    try:
        document = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionAttestationError("attestation bundle must be UTF-8 JSON") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "attestations"} or document["schema_version"] != 1:
        raise ExecutionAttestationError("invalid attestation bundle envelope")
    items = document["attestations"]
    if not isinstance(items, list) or len(items) != len(expected_nodes):
        raise ExecutionAttestationError("attestation count must match reserved participants")

    expected_set = set(expected_nodes)
    seen: set[str] = set()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    for item in items:
        claims, signature = _parse_attestation(item)
        signing_message(claims)
        if claims.node_id not in expected_set or claims.node_id in seen:
            raise ExecutionAttestationError("attestation participants do not exactly match reserved nodes")
        if claims.job_id != job_id or claims.placement_decision_id != placement_decision_id:
            raise ExecutionAttestationError("attestation job/placement binding mismatch")
        if claims.model_sha256 != model_sha256 or claims.runtime_sha256 != runtime_sha256:
            raise ExecutionAttestationError("attestation model/runtime binding mismatch")
        if claims.evidence_sha256 != evidence_sha256 or claims.output_sha256 != output_sha256:
            raise ExecutionAttestationError("attestation evidence/output binding mismatch")
        issued = datetime.fromtimestamp(claims.issued_at, tz=timezone.utc)
        expires = datetime.fromtimestamp(claims.expires_at, tz=timezone.utc)
        if expires - issued <= timedelta(0) or expires - issued > MAX_TTL:
            raise ExecutionAttestationError("attestation TTL is outside policy")
        if issued > current + clock_skew or expires <= current - clock_skew:
            raise ExecutionAttestationError("attestation is not currently valid")
        try:
            record = resolver.resolve_key(claims.node_id, claims.key_id)
        except KeyError as exc:
            raise ExecutionAttestationError("attestation uses unknown/revoked node key") from exc
        if not record.active or record.node_id != claims.node_id or record.key_id != claims.key_id:
            raise ExecutionAttestationError("attestation identity key is unavailable")
        if key_id_from_public_key(record.public_key) != record.key_id:
            raise ExecutionAttestationError("attestation public-key fingerprint mismatch")
        try:
            Ed25519PublicKey.from_public_bytes(record.public_key).verify(signature, signing_message(claims))
        except (InvalidSignature, ValueError) as exc:
            raise ExecutionAttestationError("invalid execution attestation signature") from exc
        seen.add(claims.node_id)

    if seen != expected_set:
        raise ExecutionAttestationError("not all reserved nodes attested execution")
    return tuple(node for node in expected_nodes if node in seen)
