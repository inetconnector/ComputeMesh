"""Pinned external issuer adapter for fresh hardware attestation evidence.

The helper is an operator-installed vendor integration (for example a confidential
VM + GPU attestation collector). ComputeMesh verifies the exact helper binary hash,
uses no shell, sends only node id + nonce, bounds stdout, and has no simulation
fallback. The helper's evidence is still independently verified by the client.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


MAX_ISSUER_OUTPUT_BYTES = 2 * 1024 * 1024


class VendorEvidenceIssuerError(RuntimeError):
    pass


class PinnedVendorEvidenceIssuer:
    def __init__(
        self,
        *,
        executable: Path | str,
        sha256: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        path = Path(executable)
        if path.is_symlink() or not path.is_file():
            raise ValueError("attestation issuer executable must be a regular non-symlink file")
        expected = str(sha256).lower()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError("attestation issuer SHA-256 is invalid")
        if not 0.5 <= float(timeout_seconds) <= 120.0:
            raise ValueError("attestation issuer timeout must be between 0.5 and 120 seconds")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("attestation issuer executable hash mismatch")
        self.executable = path.resolve(strict=True)
        self.sha256 = expected
        self.timeout_seconds = float(timeout_seconds)

    def issue(self, *, node_id: str, nonce: str) -> Mapping[str, Any]:
        if not isinstance(node_id, str) or not node_id or len(node_id) > 256:
            raise VendorEvidenceIssuerError("invalid attestation issuer node id")
        if not isinstance(nonce, str) or not nonce or len(nonce) > 1024:
            raise VendorEvidenceIssuerError("invalid attestation issuer nonce")
        # Recheck on every invocation so an in-place helper replacement fails closed.
        try:
            actual = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        except OSError as exc:
            raise VendorEvidenceIssuerError("attestation issuer executable is unavailable") from exc
        if actual != self.sha256:
            raise VendorEvidenceIssuerError("attestation issuer executable changed after pinning")
        request = json.dumps(
            {"schema_version": 1, "node_id": node_id, "nonce": nonce},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            result = subprocess.run(
                [str(self.executable), "issue", "--json"],
                input=request,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VendorEvidenceIssuerError("hardware attestation issuer failed to execute") from exc
        if result.returncode != 0:
            raise VendorEvidenceIssuerError("hardware attestation issuer rejected the request")
        if not result.stdout or len(result.stdout) > MAX_ISSUER_OUTPUT_BYTES:
            raise VendorEvidenceIssuerError("hardware attestation issuer returned invalid output size")
        try:
            value = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VendorEvidenceIssuerError("hardware attestation issuer returned malformed JSON") from exc
        required = {"schema_version", "technology", "measurement", "vendor_evidence", "debug_disabled"}
        if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != 1:
            raise VendorEvidenceIssuerError("hardware attestation issuer returned an invalid contract")
        technology = value.get("technology")
        measurement = value.get("measurement")
        evidence = value.get("vendor_evidence")
        if not isinstance(technology, str) or not technology.strip() or len(technology) > 128:
            raise VendorEvidenceIssuerError("hardware attestation technology is invalid")
        if technology.strip().lower() in {"simulated", "simulation", "none", "test", "mock"}:
            raise VendorEvidenceIssuerError("simulated hardware attestation is forbidden")
        if not isinstance(measurement, str) or not measurement.strip() or len(measurement) > 2048:
            raise VendorEvidenceIssuerError("hardware attestation measurement is invalid")
        if not isinstance(evidence, (dict, list)) or not evidence:
            raise VendorEvidenceIssuerError("hardware attestation evidence is missing")
        if value.get("debug_disabled") is not True:
            raise VendorEvidenceIssuerError("hardware attestation did not prove debug disabled")
        return {
            "technology": technology.strip().lower(),
            "measurement": measurement.strip(),
            "vendor_evidence": evidence,
            "debug_disabled": True,
        }
