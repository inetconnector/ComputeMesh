"""Build request-scoped P0 protected-execution evidence from bound artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.confidential.execution_gate import ProtectedExecutionEvidence
from runtime.confidential.key_release import KeyReleaseBinding, KeyReleaseError
from services.attestation.confidential_verifier import (
    ConfidentialAttestationError,
    Verifier,
    verify_confidential_attestation,
)
from services.compliance.mesh_policy import ExecutionPrivacyClass


class ProtectedContextError(RuntimeError):
    """Raised when attestation/key-release artifacts do not describe one request."""


@dataclass(frozen=True)
class ProtectedRequestContext:
    job_id: str
    privacy_class: ExecutionPrivacyClass
    node_id: str
    attestation_nonce: str
    expected_runtime_digest: str
    ciphertext_recipient_public_key: str

    def validate(self) -> None:
        for name, value in (
            ("job_id", self.job_id),
            ("node_id", self.node_id),
            ("attestation_nonce", self.attestation_nonce),
            ("expected_runtime_digest", self.expected_runtime_digest),
            ("ciphertext_recipient_public_key", self.ciphertext_recipient_public_key),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ProtectedContextError(f"{name} must be non-empty")
        if self.privacy_class is ExecutionPrivacyClass.PUBLIC:
            raise ProtectedContextError("protected request context cannot be PUBLIC")


def build_protected_execution_evidence(
    *,
    context: ProtectedRequestContext,
    attestation: Mapping[str, Any],
    verifiers: Mapping[str, Verifier],
    key_release: KeyReleaseBinding,
    encrypted_data_plane: bool,
    protected_memory: bool,
    plaintext_logging_disabled: bool,
    blinded_split_validated: bool,
    crypto_private_validated: bool = False,
) -> ProtectedExecutionEvidence:
    """Verify one attestation/key-release chain and return gate evidence.

    Technology-specific attestation cryptography remains inside the injected
    verifier.  This function enforces the cross-artifact bindings that must hold
    before content-key release and protected execution.
    """

    context.validate()
    try:
        verification = verify_confidential_attestation(
            attestation,
            verifiers=verifiers,
            expected_node_id=context.node_id,
            expected_nonce=context.attestation_nonce,
        )
    except ConfidentialAttestationError as exc:
        raise ProtectedContextError("confidential attestation envelope is invalid") from exc
    if not verification.verified:
        raise ProtectedContextError("confidential attestation was not verified")

    runtime_digest = attestation.get("runtime_digest")
    if runtime_digest != context.expected_runtime_digest:
        raise ProtectedContextError("attested runtime digest does not match requested runtime")
    ephemeral_public_key = attestation.get("ephemeral_public_key")
    if ephemeral_public_key != context.ciphertext_recipient_public_key:
        raise ProtectedContextError("ciphertext recipient is not the attested ephemeral key")

    try:
        if key_release.job_id != context.job_id:
            raise KeyReleaseError("key release job binding mismatch")
        key_release.bind_ciphertext_recipient(
            node_id=context.node_id,
            nonce=context.attestation_nonce,
            public_key=context.ciphertext_recipient_public_key,
        )
    except KeyReleaseError as exc:
        raise ProtectedContextError("content-key release binding is invalid") from exc

    return ProtectedExecutionEvidence(
        attestation_verified=True,
        attestation_fresh=True,
        debug_disabled=attestation.get("debug_disabled") is True,
        runtime_measurement_bound=True,
        ephemeral_key_bound=True,
        content_key_release_bound=True,
        encrypted_data_plane=encrypted_data_plane is True,
        protected_memory=protected_memory is True,
        plaintext_logging_disabled=plaintext_logging_disabled is True,
        blinded_split_validated=blinded_split_validated is True,
        crypto_private_validated=crypto_private_validated is True,
    )
