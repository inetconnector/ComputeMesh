"""Narrow hash-pinned process boundary for technology attestation verifiers.

ComputeMesh intentionally keeps vendor attestation SDKs out of the ordinary
provider/gateway request parser.  A production adapter may invoke a locally
provisioned helper built against the vendor's supported verifier SDK, but only
when that helper's exact executable digest matches operator policy.

The helper receives attestation evidence/metadata only.  Prompts, outputs,
content keys and model payloads must never cross this interface.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping


MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


class VerifierProcessError(RuntimeError):
    pass


@dataclass(frozen=True)
class PinnedVerifierResult:
    verified: bool
    technology: str
    nonce: str
    claims: Mapping[str, Any]


class PinnedVerifierProcess:
    """Execute one exact attestation-verifier binary with bounded JSON I/O."""

    def __init__(
        self,
        *,
        executable: Path,
        sha256: str,
        technology: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.executable = executable
        self.sha256 = sha256.lower()
        self.technology = technology.strip().lower()
        self.timeout_seconds = timeout_seconds
        if not self.technology or len(self.technology) > 128:
            raise ValueError("invalid verifier technology")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("verifier sha256 must be 64 lowercase hex characters")
        if not 0.1 <= timeout_seconds <= 120.0:
            raise ValueError("verifier timeout must be between 0.1 and 120 seconds")

    def _verified_executable(self) -> Path:
        path = self.executable.expanduser()
        if path.is_symlink() or not path.is_file():
            raise VerifierProcessError("attestation verifier must be a regular non-symlink file")
        resolved = path.resolve(strict=True)
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != self.sha256:
            raise VerifierProcessError("attestation verifier executable digest mismatch")
        if os.name != "nt" and not os.access(resolved, os.X_OK):
            raise VerifierProcessError("attestation verifier is not executable")
        return resolved

    def verify(self, request: Mapping[str, Any]) -> PinnedVerifierResult:
        if not isinstance(request, Mapping):
            raise TypeError("verifier request must be an object")
        payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_REQUEST_BYTES:
            raise VerifierProcessError("attestation verifier request exceeds size limit")
        executable = self._verified_executable()
        try:
            completed = subprocess.run(
                [str(executable)],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VerifierProcessError("attestation verifier could not complete") from exc
        if completed.returncode != 0:
            raise VerifierProcessError("attestation verifier rejected the evidence")
        if len(completed.stdout) > MAX_RESPONSE_BYTES:
            raise VerifierProcessError("attestation verifier response exceeds size limit")
        try:
            value = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VerifierProcessError("attestation verifier returned malformed JSON") from exc
        if not isinstance(value, dict) or set(value) != {
            "verified",
            "technology",
            "nonce",
            "claims",
        }:
            raise VerifierProcessError("attestation verifier returned an invalid response contract")
        verified = value.get("verified")
        technology = value.get("technology")
        nonce = value.get("nonce")
        claims = value.get("claims")
        if not isinstance(verified, bool):
            raise VerifierProcessError("attestation verifier returned invalid verified state")
        if technology != self.technology:
            raise VerifierProcessError("attestation verifier technology mismatch")
        if not isinstance(nonce, str) or not nonce or len(nonce) > 512:
            raise VerifierProcessError("attestation verifier returned invalid nonce")
        if not isinstance(claims, dict):
            raise VerifierProcessError("attestation verifier returned invalid claims")
        return PinnedVerifierResult(
            verified=verified,
            technology=technology,
            nonce=nonce,
            claims=claims,
        )
