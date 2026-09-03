"""Technology-agnostic confidential attestation validation.

Envelope validation alone never makes a node confidential. A concrete technology
verifier must be explicitly registered; unknown/simulated technologies fail closed.
For production `cmrc2` sessions the vendor-attested nonce must additionally commit
the complete content-free session boundary, not merely model/token limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from protocol.confidential_request_contract import (
    ConfidentialRequestContractError,
    SESSION_ATTESTATION_NONCE_PREFIX,
    verify_committed_session_attestation_nonce,
)


class ConfidentialAttestationError(ValueError):
    pass


Verifier = Callable[[Mapping[str, Any]], bool]


@dataclass(frozen=True)
class AttestationVerification:
    verified: bool
    technology: str
    reason: str


_REQUIRED = (
    "schema_version", "node_id", "technology", "measurement", "runtime_digest",
    "ephemeral_public_key", "nonce", "issued_at", "expires_at", "debug_disabled",
)
_SESSION_REQUIRED = (
    "account_id", "job_id", "model_id", "max_prompt_tokens", "max_completion_tokens",
    "metering_public_key", "data_plane_tls_sha256", "privacy_class", "operation",
)


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ConfidentialAttestationError(f"{label} must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfidentialAttestationError(f"{label} is not RFC3339") from exc
    if parsed.tzinfo is None:
        raise ConfidentialAttestationError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _verify_session_nonce(record: Mapping[str, Any]) -> None:
    nonce = record.get("nonce")
    if not isinstance(nonce, str) or not nonce.startswith(SESSION_ATTESTATION_NONCE_PREFIX + ":"):
        return
    missing = [key for key in _SESSION_REQUIRED if key not in record]
    if missing:
        raise ConfidentialAttestationError(
            "missing session-bound attestation fields: " + ",".join(missing)
        )
    try:
        verify_committed_session_attestation_nonce(
            nonce,
            account_id=record.get("account_id"),
            job_id=record.get("job_id"),
            model_id=record.get("model_id"),
            max_prompt_tokens=record.get("max_prompt_tokens"),
            max_completion_tokens=record.get("max_completion_tokens"),
            node_id=record.get("node_id"),
            runtime_digest=record.get("runtime_digest"),
            recipient_public_key=record.get("ephemeral_public_key"),
            metering_public_key=record.get("metering_public_key"),
            data_plane_tls_sha256=record.get("data_plane_tls_sha256"),
            privacy_class=record.get("privacy_class"),
            operation=record.get("operation"),
        )
    except ConfidentialRequestContractError as exc:
        raise ConfidentialAttestationError("attestation session commitment is invalid") from exc


def verify_confidential_attestation(
    record: Mapping[str, Any],
    *,
    verifiers: Mapping[str, Verifier],
    expected_node_id: str | None = None,
    expected_nonce: str | None = None,
    now: datetime | None = None,
) -> AttestationVerification:
    missing = [key for key in _REQUIRED if key not in record]
    if missing:
        raise ConfidentialAttestationError("missing attestation fields: " + ",".join(missing))
    if record["schema_version"] != 1:
        raise ConfidentialAttestationError("unsupported attestation schema_version")
    technology = str(record["technology"]).strip().lower()
    if expected_node_id is not None and str(record["node_id"]) != expected_node_id:
        return AttestationVerification(False, technology, "node binding mismatch")
    if expected_nonce is not None and str(record["nonce"]) != expected_nonce:
        return AttestationVerification(False, technology, "nonce binding mismatch")
    if record["debug_disabled"] is not True:
        return AttestationVerification(False, technology, "debug mode is not disabled")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    issued = _timestamp(record["issued_at"], "issued_at")
    expires = _timestamp(record["expires_at"], "expires_at")
    if issued > current or expires <= current or expires <= issued:
        return AttestationVerification(False, technology, "attestation is not current")

    # The vendor verifier proves the nonce. For cmrc2, recompute the complete
    # session digest from the public attestation fields before trusting any of
    # those fields as vendor-bound session material.
    _verify_session_nonce(record)

    verifier = verifiers.get(technology)
    if verifier is None:
        return AttestationVerification(False, technology, "no concrete verifier registered")
    try:
        ok = verifier(record) is True
    except Exception:
        ok = False
    return AttestationVerification(ok, technology, "verified" if ok else "technology verification failed")
