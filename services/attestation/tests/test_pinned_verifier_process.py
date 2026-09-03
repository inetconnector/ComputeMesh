from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from services.attestation.pinned_verifier_process import (
    PinnedVerifierProcess,
    VerifierProcessError,
)


class PinnedVerifierProcessTests(unittest.TestCase):
    def _temp_executable(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "verifier"
        path.write_bytes(b"pinned verifier bytes")
        path.chmod(0o700)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return tmp, path, digest

    def test_executable_digest_mismatch_fails_before_process_start(self) -> None:
        tmp, path, _ = self._temp_executable()
        self.addCleanup(tmp.cleanup)
        verifier = PinnedVerifierProcess(
            executable=path,
            sha256="0" * 64,
            technology="nvidia_gpu_cc",
        )
        with patch("services.attestation.pinned_verifier_process.subprocess.run") as run:
            with self.assertRaisesRegex(VerifierProcessError, "digest mismatch"):
                verifier.verify({"nonce": "n"})
            run.assert_not_called()

    def test_valid_pinned_process_contract_is_parsed(self) -> None:
        tmp, path, digest = self._temp_executable()
        self.addCleanup(tmp.cleanup)
        verifier = PinnedVerifierProcess(
            executable=path,
            sha256=digest,
            technology="nvidia_gpu_cc",
        )
        response = {
            "verified": True,
            "technology": "nvidia_gpu_cc",
            "nonce": "nonce-1",
            "claims": {"x-nvidia-overall-att-result": True},
        }
        completed = subprocess.CompletedProcess(
            args=[str(path)],
            returncode=0,
            stdout=json.dumps(response).encode("utf-8"),
            stderr=b"",
        )
        with patch(
            "services.attestation.pinned_verifier_process.subprocess.run",
            return_value=completed,
        ) as run:
            result = verifier.verify({"nonce": "nonce-1", "evidence": {"opaque": True}})
        self.assertTrue(result.verified)
        self.assertEqual(result.nonce, "nonce-1")
        args, kwargs = run.call_args
        self.assertEqual(args[0], [str(path.resolve())])
        self.assertNotIn("shell", kwargs)
        self.assertIsInstance(kwargs["input"], bytes)

    def test_nonzero_verifier_exit_fails_closed(self) -> None:
        tmp, path, digest = self._temp_executable()
        self.addCleanup(tmp.cleanup)
        verifier = PinnedVerifierProcess(
            executable=path,
            sha256=digest,
            technology="nvidia_gpu_cc",
        )
        completed = subprocess.CompletedProcess(
            args=[str(path)],
            returncode=2,
            stdout=b"",
            stderr=b"rejected",
        )
        with patch(
            "services.attestation.pinned_verifier_process.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaisesRegex(VerifierProcessError, "rejected"):
                verifier.verify({"nonce": "nonce-1"})

    def test_response_technology_substitution_is_rejected(self) -> None:
        tmp, path, digest = self._temp_executable()
        self.addCleanup(tmp.cleanup)
        verifier = PinnedVerifierProcess(
            executable=path,
            sha256=digest,
            technology="nvidia_gpu_cc",
        )
        completed = subprocess.CompletedProcess(
            args=[str(path)],
            returncode=0,
            stdout=json.dumps(
                {
                    "verified": True,
                    "technology": "generic",
                    "nonce": "nonce-1",
                    "claims": {},
                }
            ).encode("utf-8"),
            stderr=b"",
        )
        with patch(
            "services.attestation.pinned_verifier_process.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaisesRegex(VerifierProcessError, "technology mismatch"):
                verifier.verify({"nonce": "nonce-1"})


if __name__ == "__main__":
    unittest.main()
