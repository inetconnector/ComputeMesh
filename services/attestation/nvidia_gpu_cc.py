"""NVIDIA GPU Confidential Computing attestation adapter.

The cryptographic/vendor appraisal is delegated to an operator-pinned verifier
helper built against NVIDIA's supported Attestation SDK.  This module then binds
the normalized NVIDIA claims back to the ComputeMesh nonce/technology contract.

The current NVIDIA documentation recommends the C++/C Attestation SDK for new
production integrations; the legacy Python SDK is not imported here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from services.attestation.pinned_verifier_process import (
    PinnedVerifierProcess,
    VerifierProcessError,
)


NVIDIA_GPU_CC_TECHNOLOGY = "nvidia_gpu_cc"


@dataclass(frozen=True)
class NvidiaGpuAttestationPolicy:
    accepted_claim_versions: frozenset[str] = field(default_factory=lambda: frozenset({"3.0"}))
    require_submodules: bool = True


class NvidiaGpuConfidentialVerifier:
    """Technology-specific callable for `verify_confidential_attestation`."""

    def __init__(
        self,
        process: PinnedVerifierProcess,
        *,
        policy: NvidiaGpuAttestationPolicy | None = None,
    ) -> None:
        if process.technology != NVIDIA_GPU_CC_TECHNOLOGY:
            raise ValueError("NVIDIA verifier process must use nvidia_gpu_cc technology")
        self.process = process
        self.policy = policy or NvidiaGpuAttestationPolicy()
        if not self.policy.accepted_claim_versions:
            raise ValueError("at least one NVIDIA claims version must be accepted")

    def __call__(self, record: Mapping[str, Any]) -> bool:
        """Verify vendor evidence and enforce ComputeMesh/NVIDIA nonce claims.

        Any error returns False so the outer confidential-attestation verifier
        remains fail closed without leaking vendor-verifier details to callers.
        """
        try:
            return self.verify(record)
        except (ValueError, TypeError, VerifierProcessError):
            return False

    def verify(self, record: Mapping[str, Any]) -> bool:
        if not isinstance(record, Mapping):
            raise TypeError("attestation record must be an object")
        if str(record.get("technology", "")).strip().lower() != NVIDIA_GPU_CC_TECHNOLOGY:
            raise ValueError("attestation technology is not NVIDIA GPU CC")
        nonce = record.get("nonce")
        node_id = record.get("node_id")
        evidence = record.get("vendor_evidence")
        if not isinstance(nonce, str) or not nonce:
            raise ValueError("attestation nonce is missing")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("attestation node id is missing")
        if not isinstance(evidence, (dict, list)) or not evidence:
            raise ValueError("NVIDIA vendor evidence is missing")

        result = self.process.verify(
            {
                "schema_version": 1,
                "technology": NVIDIA_GPU_CC_TECHNOLOGY,
                "node_id": node_id,
                "nonce": nonce,
                "evidence": evidence,
            }
        )
        if not result.verified or result.nonce != nonce:
            return False

        claims = result.claims
        claim_version = claims.get("x-nvidia-ver")
        if claim_version not in self.policy.accepted_claim_versions:
            return False
        if claims.get("x-nvidia-overall-att-result") is not True:
            return False
        if claims.get("eat_nonce") != nonce:
            return False
        if self.policy.require_submodules:
            submodules = claims.get("submods")
            if not isinstance(submodules, dict) or not submodules:
                return False
        return True
