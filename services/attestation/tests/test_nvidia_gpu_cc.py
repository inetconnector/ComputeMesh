from __future__ import annotations

import unittest

from services.attestation.nvidia_gpu_cc import (
    NVIDIA_GPU_CC_TECHNOLOGY,
    NvidiaGpuConfidentialVerifier,
)
from services.attestation.pinned_verifier_process import PinnedVerifierResult


class _FakeProcess:
    technology = NVIDIA_GPU_CC_TECHNOLOGY

    def __init__(self, result: PinnedVerifierResult) -> None:
        self.result = result
        self.last_request = None

    def verify(self, request):
        self.last_request = request
        return self.result


class NvidiaGpuConfidentialVerifierTests(unittest.TestCase):
    def _record(self):
        return {
            "technology": NVIDIA_GPU_CC_TECHNOLOGY,
            "node_id": "node-1",
            "nonce": "nonce-1",
            "vendor_evidence": {"gpu_evidence": [{"opaque": "evidence"}]},
        }

    def _result(self, **claim_overrides):
        claims = {
            "x-nvidia-ver": "3.0",
            "x-nvidia-overall-att-result": True,
            "eat_nonce": "nonce-1",
            "submods": {"GPU-0": ["DIGEST", ["SHA256", "abc"]]},
        }
        claims.update(claim_overrides)
        return PinnedVerifierResult(
            verified=True,
            technology=NVIDIA_GPU_CC_TECHNOLOGY,
            nonce="nonce-1",
            claims=claims,
        )

    def test_verified_v3_claims_are_accepted(self) -> None:
        process = _FakeProcess(self._result())
        verifier = NvidiaGpuConfidentialVerifier(process)  # type: ignore[arg-type]
        self.assertTrue(verifier(self._record()))
        self.assertEqual(process.last_request["nonce"], "nonce-1")
        self.assertNotIn("prompt", process.last_request)

    def test_vendor_overall_failure_is_rejected(self) -> None:
        process = _FakeProcess(self._result(**{"x-nvidia-overall-att-result": False}))
        verifier = NvidiaGpuConfidentialVerifier(process)  # type: ignore[arg-type]
        self.assertFalse(verifier(self._record()))

    def test_vendor_nonce_mismatch_is_rejected(self) -> None:
        process = _FakeProcess(self._result(eat_nonce="attacker-nonce"))
        verifier = NvidiaGpuConfidentialVerifier(process)  # type: ignore[arg-type]
        self.assertFalse(verifier(self._record()))

    def test_process_nonce_mismatch_is_rejected(self) -> None:
        result = self._result()
        result = PinnedVerifierResult(
            verified=True,
            technology=NVIDIA_GPU_CC_TECHNOLOGY,
            nonce="wrong",
            claims=result.claims,
        )
        verifier = NvidiaGpuConfidentialVerifier(_FakeProcess(result))  # type: ignore[arg-type]
        self.assertFalse(verifier(self._record()))

    def test_unknown_claim_version_is_rejected(self) -> None:
        process = _FakeProcess(self._result(**{"x-nvidia-ver": "99.0"}))
        verifier = NvidiaGpuConfidentialVerifier(process)  # type: ignore[arg-type]
        self.assertFalse(verifier(self._record()))

    def test_missing_gpu_submodules_are_rejected(self) -> None:
        process = _FakeProcess(self._result(submods={}))
        verifier = NvidiaGpuConfidentialVerifier(process)  # type: ignore[arg-type]
        self.assertFalse(verifier(self._record()))

    def test_missing_vendor_evidence_fails_closed(self) -> None:
        process = _FakeProcess(self._result())
        verifier = NvidiaGpuConfidentialVerifier(process)  # type: ignore[arg-type]
        record = self._record()
        record.pop("vendor_evidence")
        self.assertFalse(verifier(record))


if __name__ == "__main__":
    unittest.main()
