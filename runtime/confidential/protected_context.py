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
    metering_public_key: str
    data_plane_tls_sha256: str

    def validate(self) -> None:
        for name, value in (
            ("job_id", self.job_id),
            ("node_id", self.node_id),
            ("attestation_nonce", self.attestation_nonce),
            ("expected_runtime_digest", self.expected_runtime_digest),
            ("ciphertext_recipient_public_key", self.ciphertext_recipient_public_key),
            ("metering_public_key", self.metering_public_key),
            ("data_plane_tls_sha256", self.data_plane_tls_sha256),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ProtectedContextError(f"{name} must be non-empty")
        if self.privacy_class is ExecutionPrivacyClass.PUBLIC:
            raise ProtectedContextError("protected request context cannot be PUBLIC")
        if not self.data_plane_tls_sha256.startswith("sha256:") or len(self.data_plane_tls_sha256) != 71:
            raise ProtectedContextError("data_plane_tls_sha256 must be a sha256 fingerprint")
        digest = self.data_plane_tls_sha256.removeprefix("sha256:")
        if any(ch not in "0123456789abcdef" for ch in digest):
            raise ProtectedContextError("data_plane_tls_sha256 must be lowercase hex")


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
    """Verify one attestation/key-release chain and return gate evidence."""

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

    if attestation.get("runtime_digest") != context.expected_runtime_digest:
        raise ProtectedContextError("attested runtime digest does not match requested runtime")
    if attestation.get("ephemeral_public_key") != context.ciphertext_recipient_public_key:
        raise ProtectedContextError("ciphertext recipient is not the attested ephemeral key")
    if attestation.get("metering_public_key") != context.metering_public_key:
        raise ProtectedContextError("metering key is not bound to the attestation")
    if attestation.get("data_plane_tls_sha256") != context.data_plane_tls_sha256:
        raise ProtectedContextError("data-plane TLS identity is not bound to the attestation")

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
