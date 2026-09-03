"""Local OpenAI-compatible bridge for ComputeMesh protected inference.

The application-facing side stays OpenAI-compatible.  Protected ComputeMesh
session/attestation/envelope calls are transport internals and never require the
application to understand ComputeMesh cryptography.

Security boundary:
- request plaintext is accepted only on the local trusted side;
- fresh remote attestation is verified locally against operator policy;
- the original OpenAI request JSON is encrypted before network egress;
- the remote gateway receives ciphertext only;
- protected response plaintext is recovered only on the local trusted side.

This module deliberately contains no prompt/output logging.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import ssl
from typing import Any, Mapping, Protocol
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    ConfidentialEnvelopeError,
    ConfidentialResponseEnvelope,
    create_confidential_request,
    decrypt_confidential_response,
)
from protocol.confidential_request_contract import (
    ConfidentialRequestContractError,
    verify_committed_attestation_nonce,
)
from services.attestation.confidential_verifier import (
    ConfidentialAttestationError,
    Verifier,
    verify_confidential_attestation,
)
from services.attestation.nvidia_gpu_cc import (
    NVIDIA_GPU_CC_TECHNOLOGY,
    NvidiaGpuAttestationPolicy,
    NvidiaGpuConfidentialVerifier,
)
from services.attestation.pinned_verifier_process import PinnedVerifierProcess
from services.common.secure_memory import secure_zero_memory


MAX_OPENAI_BODY_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_COMPLETION_TOKENS = 1024
INTERNAL_SESSION_PATH = "/internal/v1/confidential/sessions"
INTERNAL_COMPLETION_PATH = "/internal/v1/confidential/chat/completions"


class ConfidentialOpenAIError(RuntimeError):
    """Fail-closed local bridge error suitable for OpenAI-shaped translation."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 503,
        error_type: str = "confidential_execution_unavailable",
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = int(status)
        self.error_type = error_type
        self.param = param
        self.code = code

    def openai_error(self) -> dict[str, Any]:
        return {
            "error": {
                "message": str(self),
                "type": self.error_type,
                "param": self.param,
                "code": self.code,
            }
        }


@dataclass(frozen=True)
class LocalAttestationPolicy:
    verifiers: Mapping[str, Verifier]
    allowed_runtime_digests: frozenset[str]

    def verify_descriptor(self, descriptor: Mapping[str, Any]) -> None:
        session = descriptor.get("session")
        account_id = descriptor.get("account_id")
        if not isinstance(session, Mapping) or not isinstance(account_id, str) or not account_id:
            raise ConfidentialOpenAIError("Protected session descriptor is invalid")
        attestation = session.get("attestation")
        if not isinstance(attestation, Mapping):
            raise ConfidentialOpenAIError("Protected session attestation is missing")
        node_id = session.get("node_id")
        nonce = session.get("attestation_nonce")
        runtime_digest = session.get("runtime_digest")
        if not isinstance(node_id, str) or not node_id:
            raise ConfidentialOpenAIError("Protected session node identity is invalid")
        if not isinstance(nonce, str) or not nonce:
            raise ConfidentialOpenAIError("Protected session attestation nonce is invalid")
        if not isinstance(runtime_digest, str) or runtime_digest not in self.allowed_runtime_digests:
            raise ConfidentialOpenAIError("Protected runtime is not locally approved")
        try:
            verification = verify_confidential_attestation(
                attestation,
                verifiers=self.verifiers,
                expected_node_id=node_id,
                expected_nonce=nonce,
            )
        except ConfidentialAttestationError as exc:
            raise ConfidentialOpenAIError("Protected attestation is invalid") from exc
        if not verification.verified:
            raise ConfidentialOpenAIError("Protected attestation could not be verified")

        exact_bindings = {
            "runtime_digest": "runtime_digest",
            "ephemeral_public_key": "recipient_public_key",
            "metering_public_key": "metering_public_key",
            "data_plane_tls_sha256": "data_plane_tls_sha256",
            "node_id": "node_id",
            "nonce": "attestation_nonce",
        }
        for attestation_name, session_name in exact_bindings.items():
            if attestation.get(attestation_name) != session.get(session_name):
                raise ConfidentialOpenAIError(
                    f"Protected attestation {attestation_name} binding mismatch"
                )


def load_local_attestation_policy(path: Path) -> LocalAttestationPolicy:
    """Load local trust policy.  Unknown technologies fail closed.

    Current supported concrete verifier entry:

    {
      "allowed_runtime_digests": ["sha256:..."],
      "technologies": {
        "nvidia_gpu_cc": {
          "executable": "/opt/computemesh/nvat-helper",
          "sha256": "<64 hex>",
          "accepted_claim_versions": ["3.0"],
          "require_submodules": true
        }
      }
    }
    """
    policy_path = Path(path).expanduser()
    if policy_path.is_symlink() or not policy_path.is_file():
        raise ConfidentialOpenAIError("Local attestation policy must be a regular non-symlink file")
    try:
        value = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfidentialOpenAIError("Local attestation policy could not be loaded") from exc
    if not isinstance(value, dict) or set(value) != {"allowed_runtime_digests", "technologies"}:
        raise ConfidentialOpenAIError("Local attestation policy contract is invalid")
    runtime_values = value.get("allowed_runtime_digests")
    technologies = value.get("technologies")
    if not isinstance(runtime_values, list) or not runtime_values:
        raise ConfidentialOpenAIError("At least one local runtime digest must be approved")
    runtimes = frozenset(str(item) for item in runtime_values if isinstance(item, str) and item)
    if len(runtimes) != len(runtime_values):
        raise ConfidentialOpenAIError("Local runtime digest policy is invalid")
    if not isinstance(technologies, dict) or not technologies:
        raise ConfidentialOpenAIError("At least one concrete attestation technology is required")

    verifiers: dict[str, Verifier] = {}
    for technology, config in technologies.items():
        if technology != NVIDIA_GPU_CC_TECHNOLOGY:
            raise ConfidentialOpenAIError(
                f"No locally supported concrete verifier for technology {technology!r}"
            )
        if not isinstance(config, dict):
            raise ConfidentialOpenAIError("NVIDIA attestation policy is invalid")
        executable = config.get("executable")
        sha256 = config.get("sha256")
        versions = config.get("accepted_claim_versions", ["3.0"])
        require_submodules = config.get("require_submodules", True)
        if not isinstance(executable, str) or not executable:
            raise ConfidentialOpenAIError("NVIDIA verifier executable is required")
        if not isinstance(sha256, str):
            raise ConfidentialOpenAIError("NVIDIA verifier SHA-256 is required")
        if not isinstance(versions, list) or not versions or not all(isinstance(v, str) and v for v in versions):
            raise ConfidentialOpenAIError("NVIDIA accepted claim versions are invalid")
        if not isinstance(require_submodules, bool):
            raise ConfidentialOpenAIError("NVIDIA require_submodules must be boolean")
        try:
            process = PinnedVerifierProcess(
                executable=Path(executable),
                sha256=sha256,
                technology=NVIDIA_GPU_CC_TECHNOLOGY,
            )
            verifiers[technology] = NvidiaGpuConfidentialVerifier(
                process,
                policy=NvidiaGpuAttestationPolicy(
                    accepted_claim_versions=frozenset(versions),
                    require_submodules=require_submodules,
                ),
            )
        except (ValueError, TypeError) as exc:
            raise ConfidentialOpenAIError("NVIDIA attestation policy is invalid") from exc
    return LocalAttestationPolicy(verifiers=verifiers, allowed_runtime_digests=runtimes)


class ProtectedTransport(Protocol):
    def create_session(
        self,
        *,
        authorization: str,
        model: str,
        privacy_class: str,
        max_prompt_tokens: int,
        max_completion_tokens: int,
    ) -> Mapping[str, Any]: ...

    def execute(
        self,
        *,
        authorization: str,
        privacy_class: str,
        envelope: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def get_models(self, *, authorization: str) -> tuple[int, bytes, str]: ...


class HttpProtectedTransport:
    """Remote ComputeMesh transport.  It never receives OpenAI plaintext."""

    def __init__(
        self,
        *,
        base_url: str,
        ca_file: Path | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        parsed = urlparse.urlparse(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Protected remote base_url must use HTTPS")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("Protected remote base_url must not contain credentials/query/fragment")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        if not 1.0 <= self.timeout_seconds <= 300.0:
            raise ValueError("Protected remote timeout must be between 1 and 300 seconds")
        self.ssl_context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    def _json_request(
        self,
        path: str,
        *,
        authorization: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urlrequest.Request(
            self.base_url + path,
            data=raw,
            method="POST",
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Content-Length": str(len(raw)),
                "User-Agent": "ComputeMesh-Local-OpenAI-Proxy/1",
            },
        )
        try:
            with urlrequest.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                response_raw = response.read(MAX_OPENAI_BODY_BYTES + 1)
        except urlerror.HTTPError as exc:
            # Never relay private control-plane details; only status survives.
            raise ConfidentialOpenAIError(
                "Protected ComputeMesh transport rejected the request",
                status=exc.code if 400 <= exc.code <= 599 else 502,
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise ConfidentialOpenAIError("Protected ComputeMesh transport is unavailable") from exc
        if len(response_raw) > MAX_OPENAI_BODY_BYTES:
            raise ConfidentialOpenAIError("Protected transport response exceeds size limit", status=502)
        try:
            value = json.loads(response_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfidentialOpenAIError("Protected transport returned malformed JSON", status=502) from exc
        if not isinstance(value, dict):
            raise ConfidentialOpenAIError("Protected transport returned invalid JSON", status=502)
        return value

    def create_session(
        self,
        *,
        authorization: str,
        model: str,
        privacy_class: str,
        max_prompt_tokens: int,
        max_completion_tokens: int,
    ) -> Mapping[str, Any]:
        return self._json_request(
            INTERNAL_SESSION_PATH,
            authorization=authorization,
            body={
                "model": model,
                "privacy_class": privacy_class,
                "operation": "chat_completion",
                "max_prompt_tokens": max_prompt_tokens,
                "max_completion_tokens": max_completion_tokens,
            },
        )

    def execute(
        self,
        *,
        authorization: str,
        privacy_class: str,
        envelope: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._json_request(
            INTERNAL_COMPLETION_PATH,
            authorization=authorization,
            body={"computemesh_privacy": privacy_class, "envelope": dict(envelope)},
        )

    def get_models(self, *, authorization: str) -> tuple[int, bytes, str]:
        request = urlrequest.Request(
            self.base_url + "/v1/models",
            method="GET",
            headers={"Authorization": authorization, "Accept": "application/json"},
        )
        try:
            with urlrequest.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                raw = response.read(MAX_OPENAI_BODY_BYTES + 1)
                content_type = response.headers.get("Content-Type", "application/json")
                status = int(response.status)
        except urlerror.HTTPError as exc:
            raw = exc.read(MAX_OPENAI_BODY_BYTES + 1)
            return exc.code, raw, exc.headers.get("Content-Type", "application/json")
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise ConfidentialOpenAIError("ComputeMesh model catalog is unavailable") from exc
        if len(raw) > MAX_OPENAI_BODY_BYTES:
            raise ConfidentialOpenAIError("ComputeMesh model catalog response is too large", status=502)
        return status, raw, content_type


@dataclass(frozen=True)
class PreparedOpenAIRequest:
    body: Mapping[str, Any]
    encoded: bytes
    model: str
    stream: bool
    max_prompt_tokens: int
    max_completion_tokens: int


def prepare_openai_chat_request(body: Mapping[str, Any]) -> PreparedOpenAIRequest:
    if not isinstance(body, Mapping):
        raise ConfidentialOpenAIError(
            "Request body must be a JSON object",
            status=400,
            error_type="invalid_request_error",
        )
    model = body.get("model")
    messages = body.get("messages")
    if not isinstance(model, str) or not model.strip():
        raise ConfidentialOpenAIError(
            "Missing required parameter: model",
            status=400,
            error_type="invalid_request_error",
            param="model",
        )
    if not isinstance(messages, list):
        raise ConfidentialOpenAIError(
            "Missing required parameter: messages",
            status=400,
            error_type="invalid_request_error",
            param="messages",
        )
    stream_value = body.get("stream", False)
    if not isinstance(stream_value, bool):
        raise ConfidentialOpenAIError(
            "stream must be a boolean",
            status=400,
            error_type="invalid_request_error",
            param="stream",
        )
    legacy = body.get("max_tokens")
    modern = body.get("max_completion_tokens")
    if legacy is not None and modern is not None and legacy != modern:
        raise ConfidentialOpenAIError(
            "max_tokens and max_completion_tokens conflict",
            status=400,
            error_type="invalid_request_error",
            param="max_completion_tokens",
        )
    completion_value = modern if modern is not None else legacy
    if completion_value is None:
        max_completion = DEFAULT_MAX_COMPLETION_TOKENS
    elif isinstance(completion_value, int) and not isinstance(completion_value, bool) and 1 <= completion_value <= 1_000_000:
        max_completion = completion_value
    else:
        raise ConfidentialOpenAIError(
            "Invalid completion token limit",
            status=400,
            error_type="invalid_request_error",
            param="max_completion_tokens",
        )
    try:
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ConfidentialOpenAIError(
            "Request contains non-JSON values",
            status=400,
            error_type="invalid_request_error",
        ) from exc
    if len(encoded) > MAX_OPENAI_BODY_BYTES:
        raise ConfidentialOpenAIError("Request is too large", status=413, error_type="invalid_request_error")
    # Conservative pre-content reservation: a byte-level upper bound plus protocol
    # overhead.  The signed TEE usage receipt later settles actual token counts and
    # refunds unused escrow.  No content is sent during admission.
    max_prompt = min(1_000_000, max(1, len(encoded) + 1024))
    return PreparedOpenAIRequest(
        body=dict(body),
        encoded=encoded,
        model=model.strip(),
        stream=stream_value,
        max_prompt_tokens=max_prompt,
        max_completion_tokens=max_completion,
    )


class ConfidentialOpenAIBridge:
    def __init__(
        self,
        *,
        transport: ProtectedTransport,
        attestation_policy: LocalAttestationPolicy,
        privacy_class: str = "CONFIDENTIAL",
    ) -> None:
        if privacy_class not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
            raise ValueError("privacy_class must be CONFIDENTIAL or CRYPTO_PRIVATE")
        self.transport = transport
        self.attestation_policy = attestation_policy
        self.privacy_class = privacy_class

    def complete(
        self,
        *,
        authorization: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        prepared = prepare_openai_chat_request(body)
        if prepared.stream:
            raise ConfidentialOpenAIError(
                "Protected streaming requires the encrypted stream transport",
                status=501,
                error_type="invalid_request_error",
                param="stream",
                code="protected_stream_transport_required",
            )
        descriptor = self.transport.create_session(
            authorization=authorization,
            model=prepared.model,
            privacy_class=self.privacy_class,
            max_prompt_tokens=prepared.max_prompt_tokens,
            max_completion_tokens=prepared.max_completion_tokens,
        )
        self.attestation_policy.verify_descriptor(descriptor)
        session = descriptor.get("session")
        account_id = descriptor.get("account_id")
        assert isinstance(session, Mapping)
        assert isinstance(account_id, str)
        if session.get("model_id") != prepared.model:
            raise ConfidentialOpenAIError("Protected session model binding mismatch")
        if session.get("privacy_class") != self.privacy_class:
            raise ConfidentialOpenAIError("Protected session privacy binding mismatch")
        if session.get("operation") != "chat_completion":
            raise ConfidentialOpenAIError("Protected session operation binding mismatch")
        if session.get("max_prompt_tokens") != prepared.max_prompt_tokens:
            raise ConfidentialOpenAIError("Protected session prompt reservation mismatch")
        if session.get("max_completion_tokens") != prepared.max_completion_tokens:
            raise ConfidentialOpenAIError("Protected session completion reservation mismatch")
        try:
            verify_committed_attestation_nonce(
                str(session.get("attestation_nonce", "")),
                model_id=prepared.model,
                max_prompt_tokens=prepared.max_prompt_tokens,
                max_completion_tokens=prepared.max_completion_tokens,
            )
        except ConfidentialRequestContractError as exc:
            raise ConfidentialOpenAIError(
                "Protected session request contract is not attestation-bound"
            ) from exc

        binding = ConfidentialBinding(
            account_id=account_id,
            job_id=str(session.get("job_id", "")),
            node_id=str(session.get("node_id", "")),
            attestation_nonce=str(session.get("attestation_nonce", "")),
            runtime_digest=str(session.get("runtime_digest", "")),
            data_plane_tls_sha256=str(session.get("data_plane_tls_sha256", "")),
            privacy_class=self.privacy_class,
            operation="chat_completion",
        )
        recipient_key = session.get("recipient_public_key")
        if not isinstance(recipient_key, str) or not recipient_key:
            raise ConfidentialOpenAIError("Protected session recipient key is invalid")
        try:
            envelope, client_context = create_confidential_request(
                prepared.encoded,
                recipient_public_key=recipient_key,
                binding=binding,
            )
        except ConfidentialEnvelopeError as exc:
            raise ConfidentialOpenAIError("Protected request encryption failed") from exc
        try:
            result = self.transport.execute(
                authorization=authorization,
                privacy_class=self.privacy_class,
                envelope=envelope.to_dict(),
            )
            response_value = result.get("response")
            if not isinstance(response_value, Mapping):
                raise ConfidentialOpenAIError("Protected response envelope is missing", status=502)
            try:
                response_envelope = ConfidentialResponseEnvelope.from_dict(response_value)
                plaintext = decrypt_confidential_response(
                    response_envelope,
                    client_context=client_context,
                )
            except ConfidentialEnvelopeError as exc:
                raise ConfidentialOpenAIError("Protected response authentication failed", status=502) from exc
            try:
                if len(plaintext) > MAX_OPENAI_BODY_BYTES:
                    raise ConfidentialOpenAIError("Protected OpenAI response is too large", status=502)
                try:
                    openai_response = json.loads(memoryview(plaintext).tobytes().decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ConfidentialOpenAIError("Protected runtime returned malformed OpenAI JSON", status=502) from exc
            finally:
                secure_zero_memory(plaintext)
            _validate_openai_completion_response(openai_response)
            return openai_response
        finally:
            client_context.close()


def _validate_openai_completion_response(value: Any) -> None:
    if not isinstance(value, dict):
        raise ConfidentialOpenAIError("Protected runtime returned invalid OpenAI response", status=502)
    if not isinstance(value.get("id"), str) or not value.get("id"):
        raise ConfidentialOpenAIError("Protected runtime response id is invalid", status=502)
    if value.get("object") != "chat.completion":
        raise ConfidentialOpenAIError("Protected runtime response object is invalid", status=502)
    if not isinstance(value.get("created"), int):
        raise ConfidentialOpenAIError("Protected runtime response created field is invalid", status=502)
    if not isinstance(value.get("model"), str) or not value.get("model"):
        raise ConfidentialOpenAIError("Protected runtime response model is invalid", status=502)
    choices = value.get("choices")
    if not isinstance(choices, list):
        raise ConfidentialOpenAIError("Protected runtime response choices are invalid", status=502)
    for choice in choices:
        if not isinstance(choice, dict) or not isinstance(choice.get("index"), int):
            raise ConfidentialOpenAIError("Protected runtime response choice is invalid", status=502)
        if not isinstance(choice.get("message"), dict):
            raise ConfidentialOpenAIError("Protected runtime response message is invalid", status=502)


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "::1", "localhost"}
