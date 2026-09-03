"""Fail-closed P0 gate for protected ComputeMesh execution.

This module is intentionally independent of any single TEE vendor.  A protected
request may proceed only when the runtime can present evidence for every
mandatory protection in the requested privacy class.  Merely enabling a feature
flag or selecting a trusted provider is never enough.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.compliance.mesh_policy import ExecutionPrivacyClass


class ProtectedExecutionUnavailable(RuntimeError):
    """Raised before protected plaintext execution when mandatory controls are absent."""


@dataclass(frozen=True)
class ProtectedExecutionEvidence:
    """Request-scoped evidence for the complete protected-execution chain."""

    attestation_verified: bool = False
    attestation_fresh: bool = False
    debug_disabled: bool = False
    runtime_measurement_bound: bool = False
    ephemeral_key_bound: bool = False
    content_key_release_bound: bool = False
    encrypted_data_plane: bool = False
    protected_memory: bool = False
    plaintext_logging_disabled: bool = False
    blinded_split_validated: bool = False
    crypto_private_validated: bool = False


@dataclass(frozen=True)
class ProtectedExecutionDecision:
    allowed: bool
    privacy_class: ExecutionPrivacyClass
    missing: tuple[str, ...]
    reason: str


_CONFIDENTIAL_REQUIREMENTS = (
    "attestation_verified",
    "attestation_fresh",
    "debug_disabled",
    "runtime_measurement_bound",
    "ephemeral_key_bound",
    "content_key_release_bound",
    "encrypted_data_plane",
    "protected_memory",
    "plaintext_logging_disabled",
    "blinded_split_validated",
)


def evaluate_protected_execution(
    privacy_class: ExecutionPrivacyClass,
    evidence: ProtectedExecutionEvidence,
) -> ProtectedExecutionDecision:
    """Return a deterministic decision without ever weakening the requested class."""

    if privacy_class is ExecutionPrivacyClass.PUBLIC:
        return ProtectedExecutionDecision(
            allowed=True,
            privacy_class=privacy_class,
            missing=(),
            reason="PUBLIC execution does not claim confidential processing",
        )

    required = list(_CONFIDENTIAL_REQUIREMENTS)
    if privacy_class is ExecutionPrivacyClass.CRYPTO_PRIVATE:
        required.append("crypto_private_validated")
    elif privacy_class is not ExecutionPrivacyClass.CONFIDENTIAL:
        return ProtectedExecutionDecision(
            allowed=False,
            privacy_class=privacy_class,
            missing=("supported_privacy_class",),
            reason="unsupported protected privacy class",
        )

    missing = tuple(name for name in required if getattr(evidence, name) is not True)
    if missing:
        return ProtectedExecutionDecision(
            allowed=False,
            privacy_class=privacy_class,
            missing=missing,
            reason="protected execution chain is incomplete: " + ",".join(missing),
        )
    return ProtectedExecutionDecision(
        allowed=True,
        privacy_class=privacy_class,
        missing=(),
        reason=f"{privacy_class.value} execution passed the complete P0 gate",
    )


def require_protected_execution(
    privacy_class: ExecutionPrivacyClass,
    evidence: ProtectedExecutionEvidence,
) -> ProtectedExecutionDecision:
    """Fail closed before protected execution if any mandatory control is missing."""

    decision = evaluate_protected_execution(privacy_class, evidence)
    if not decision.allowed:
        raise ProtectedExecutionUnavailable(decision.reason)
    return decision
