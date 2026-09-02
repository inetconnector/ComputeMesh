"""Controlled local llama.cpp GPU work for hardware-promo verification.

This module is intentionally narrow. The remote challenge may choose only bounded
workload parameters (prompt/seed/token count) and expected identities. Executable,
model path, runtime backend, device and accelerator identity are configured locally
by the GPU operator and are never accepted from a remote request.

The v1 challenge is vendor-neutral across the supported llama.cpp GPU backends.
NVIDIA/CUDA and AMD through ROCm/HIP or Vulkan use the same proof contract. There is
no GPU model allowlist: the configured local llama.cpp runtime is the capability
probe. An unsupported device must fail closed rather than falling back to CPU.
A successful response is evidence that the enrolled provider agent completed the
configured llama.cpp workload under explicit full GPU offload; it is not
hardware-rooted remote attestation and must still be combined with server-observed
timing, durable anti-replay state and private fraud policy.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.node_identity import key_id_from_public_key
from runtime.llama.rpc_spike import (
    RpcSpikeError,
    SpikePlan,
    _json_request,
    build_coordinator_command,
    completion_payload,
    parse_completion_response,
    parse_runtime_build_identity,
    runtime_build_matches,
    runtime_version,
    sha256_file,
    wait_until_ready,
)

GPU_PROMO_CAPABILITY = "gpu_promo_challenge_v1"
PROMO_PROOF_DOMAIN = b"ComputeMesh.PromoProof.v1\x00"
SUPPORTED_GPU_PROMO_BACKENDS = frozenset({"cuda", "rocm", "vulkan"})
_DEVICE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class GpuPromoChallengeError(RuntimeError):
    pass


def normalize_gpu_promo_backend(value: str) -> str:
    backend = str(value or "").strip().lower()
    aliases = {"hip": "rocm", "amd": "rocm", "nvidia": "cuda"}
    backend = aliases.get(backend, backend)
    if backend not in SUPPORTED_GPU_PROMO_BACKENDS:
        raise ValueError(
            "runtime_backend must be one of: " + ", ".join(sorted(SUPPORTED_GPU_PROMO_BACKENDS))
        )
    return backend


def validate_local_llama_device(value: str) -> str:
    """Validate a locally selected llama.cpp device identifier without vendor assumptions.

    Device names are passed as one subprocess argument, never through a shell. The
    actual llama.cpp start with ``--device`` and ``--n-gpu-layers all`` is the final
    capability check, so unknown/unsupported cards fail closed at runtime.
    """
    device = str(value or "").strip()
    if _DEVICE_RE.fullmatch(device) is None:
        raise ValueError("promo device must be a safe explicit llama.cpp GPU device identifier")
    if device.upper().startswith("RPC") or device.upper() in {"CPU", "NONE"}:
        raise ValueError("promo device must identify a local GPU accelerator")
    return device


@dataclass(frozen=True)
class GpuPromoChallengeConfig:
    llama_server: Path
    model: Path
    device: str
    accelerator_id: str
    runtime_backend: str = "cuda"
    local_port: int = 18090
    context_size: int = 2048
    max_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not self.llama_server.is_file() or self.llama_server.is_symlink():
            raise ValueError("promo llama-server must be a local non-symlink file")
        if not self.model.is_file() or self.model.is_symlink():
            raise ValueError("promo challenge model must be a local non-symlink file")
        object.__setattr__(self, "device", validate_local_llama_device(self.device))
        object.__setattr__(self, "runtime_backend", normalize_gpu_promo_backend(self.runtime_backend))
        accelerator = str(self.accelerator_id or "").strip()
        if not accelerator or len(accelerator) > 256:
            raise ValueError("accelerator_id must be 1..256 characters")
        if not 1 <= self.local_port <= 65535:
            raise ValueError("local_port must be 1..65535")
        if not 128 <= self.context_size <= 32768:
            raise ValueError("promo context_size must be 128..32768")
        if not 1 <= self.max_timeout_seconds <= 300:
            raise ValueError("max_timeout_seconds must be 1..300")


@dataclass(frozen=True)
class GpuPromoWorkResult:
    accelerator_id: str
    runtime_backend: str
    runtime_build: str
    work_digest: str
    elapsed_ms: float


def _require_text(value: Any, *, field: str, max_len: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_len:
        raise GpuPromoChallengeError(f"invalid {field}")
    return text


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def promo_proof_signing_message(proof: Mapping[str, Any]) -> bytes:
    """Canonical signing message matching the private promo verifier v1."""
    document = {
        "challenge_id": proof["challenge_id"],
        "claim_class": proof["claim_class"],
        "owner_id": proof["owner_id"],
        "node_id": proof["node_id"],
        "key_id": proof["key_id"],
        "hardware_claim_id": proof["hardware_claim_id"],
        "evidence_digest": proof["evidence_digest"],
        "nonce": proof["nonce"],
        "assurance_tier": proof["assurance_tier"],
        "accelerator_id": proof["accelerator_id"],
        "runtime_backend": proof["runtime_backend"],
        "runtime_build": proof["runtime_build"],
        "work_digest": proof["work_digest"],
        "elapsed_ms": round(float(proof["elapsed_ms"]), 6),
    }
    raw = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return PROMO_PROOF_DOMAIN + raw


def build_signed_gpu_promo_proof(
    *,
    challenge: Mapping[str, Any],
    result: GpuPromoWorkResult,
    private_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    """Bind successful GPU work to the enrolled node key and promo nonce."""
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    key_id = key_id_from_public_key(public_key)
    if str(challenge.get("claim_class")) != "gpu_onboarding":
        raise GpuPromoChallengeError("GPU challenge has the wrong claim class")
    if str(challenge.get("key_id")) != key_id:
        raise GpuPromoChallengeError("GPU challenge key_id does not match enrolled node key")

    proof: dict[str, Any] = {
        "challenge_id": _require_text(
            challenge.get("challenge_id"), field="challenge_id", max_len=256
        ),
        "claim_class": "gpu_onboarding",
        "owner_id": _require_text(challenge.get("owner_id"), field="owner_id", max_len=256),
        "node_id": _require_text(challenge.get("node_id"), field="node_id", max_len=128),
        "key_id": key_id,
        "hardware_claim_id": _require_text(
            challenge.get("hardware_claim_id"), field="hardware_claim_id", max_len=512
        ),
        "evidence_digest": _require_text(
            challenge.get("evidence_digest"), field="evidence_digest", max_len=128
        ),
        "nonce": _require_text(challenge.get("nonce"), field="nonce", max_len=256),
        "assurance_tier": "MULTI_SIGNAL_VERIFIED",
        "public_key_b64u": _b64u(public_key),
        "signature_b64u": "",
        "accelerator_id": result.accelerator_id,
        "runtime_backend": result.runtime_backend,
        "runtime_build": result.runtime_build,
        "work_digest": result.work_digest,
        "elapsed_ms": round(float(result.elapsed_ms), 6),
    }
    proof["signature_b64u"] = _b64u(private_key.sign(promo_proof_signing_message(proof)))
    return proof


class GpuPromoChallengeRunner:
    """Run one deterministic local llama.cpp workload with full GPU offload."""

    def __init__(self, config: GpuPromoChallengeConfig) -> None:
        self.config = config
        self._lock = threading.Lock()

    def run(self, challenge: Mapping[str, Any]) -> GpuPromoWorkResult:
        if not isinstance(challenge, Mapping):
            raise GpuPromoChallengeError("GPU challenge must be an object")
        if str(challenge.get("node_id") or "").strip() == "":
            raise GpuPromoChallengeError("GPU challenge lacks node_id")

        prompt = str(challenge.get("prompt") or "")
        if not 1 <= len(prompt.encode("utf-8")) <= 4096:
            raise GpuPromoChallengeError("GPU challenge prompt exceeds bounds")
        seed = challenge.get("seed")
        n_predict = challenge.get("n_predict")
        timeout_ms = challenge.get("timeout_ms")
        expected_build_number = challenge.get("expected_llama_build_number")
        expected_build_commit = str(challenge.get("expected_llama_build_commit") or "")
        expected_model_sha = str(challenge.get("model_sha256") or "")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
            raise GpuPromoChallengeError("invalid GPU challenge seed")
        if isinstance(n_predict, bool) or not isinstance(n_predict, int) or not 8 <= n_predict <= 128:
            raise GpuPromoChallengeError("invalid GPU challenge n_predict")
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1000 <= timeout_ms <= 300000
        ):
            raise GpuPromoChallengeError("invalid GPU challenge timeout_ms")
        if (
            isinstance(expected_build_number, bool)
            or not isinstance(expected_build_number, int)
            or expected_build_number < 1
            or _COMMIT_RE.fullmatch(expected_build_commit) is None
        ):
            raise GpuPromoChallengeError("invalid expected llama.cpp build identity")
        if _HEX64_RE.fullmatch(expected_model_sha) is None:
            raise GpuPromoChallengeError("invalid expected model digest")

        timeout_seconds = min(timeout_ms / 1000.0, self.config.max_timeout_seconds)
        if not self._lock.acquire(blocking=False):
            raise GpuPromoChallengeError("another GPU promo challenge is already running")
        process: subprocess.Popen[bytes] | None = None
        try:
            local_model_sha = sha256_file(self.config.model)
            if local_model_sha != expected_model_sha:
                raise GpuPromoChallengeError("local promo model digest does not match challenge")
            version_text = runtime_version(self.config.llama_server)
            build = parse_runtime_build_identity(version_text)
            if not runtime_build_matches(
                build,
                expected_number=expected_build_number,
                expected_commit=expected_build_commit,
            ):
                raise GpuPromoChallengeError("local llama.cpp build does not match challenge")

            plan = SpikePlan(
                llama_server=self.config.llama_server,
                model=self.config.model,
                rpc_endpoints=(),
                devices=(self.config.device,),
                tensor_split=(1.0,),
                mode="local_baseline",
                local_port=self.config.local_port,
                context_size=self.config.context_size,
                n_predict=n_predict,
                seed=seed,
            )
            command = build_coordinator_command(plan)
            # The selected device is local-only. ``build_coordinator_command`` passes
            # it as one argv value and forces ``--n-gpu-layers all``. Unsupported GPU
            # backends/devices therefore fail during real llama.cpp startup.
            overall_start = time.monotonic()
            deadline = overall_start + timeout_seconds
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GpuPromoChallengeError("GPU challenge timed out before model startup")
            wait_until_ready(
                self.config.local_port,
                timeout=remaining,
                process=process,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GpuPromoChallengeError("GPU challenge timed out before inference")
            request_start = time.monotonic()
            response = _json_request(
                "POST",
                f"http://127.0.0.1:{self.config.local_port}/completion",
                completion_payload(prompt, n_predict=n_predict, seed=seed),
                remaining,
            )
            request_ms = (time.monotonic() - request_start) * 1000.0
            content, tokens, timings = parse_completion_response(response)
            if tokens:
                digest_bytes = json.dumps(tokens, separators=(",", ":")).encode("ascii")
            else:
                digest_bytes = content.encode("utf-8")
            work_digest = "sha256:" + hashlib.sha256(digest_bytes).hexdigest()
            predicted_n = timings.get("predicted_n")
            if (
                isinstance(predicted_n, bool)
                or not isinstance(predicted_n, (int, float))
                or predicted_n <= 0
            ):
                raise GpuPromoChallengeError("llama.cpp challenge generated no tokens")
            runtime_build = (
                f"llama.cpp:{build.build_number}:{build.commit};"
                f"model_sha256:{local_model_sha};backend:{self.config.runtime_backend};"
                f"device:{self.config.device}"
            )
            return GpuPromoWorkResult(
                accelerator_id=self.config.accelerator_id,
                runtime_backend=self.config.runtime_backend,
                runtime_build=runtime_build,
                work_digest=work_digest,
                elapsed_ms=request_ms,
            )
        except RpcSpikeError as exc:
            raise GpuPromoChallengeError(str(exc)) from exc
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self._lock.release()
