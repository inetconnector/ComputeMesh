"""Technology-agnostic confidential attestation validation.

Envelope validation alone never makes a node confidential. A concrete
technology verifier must be explicitly registered; unknown/simulated
technologies fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping


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
    verifier = verifiers.get(technology)
    if verifier is None:
        return AttestationVerification(False, technology, "no concrete verifier registered")
    try:
        ok = verifier(record) is True
    except Exception:
        ok = False
    return AttestationVerification(ok, technology, "verified" if ok else "technology verification failed")
