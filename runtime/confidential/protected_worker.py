"""Provider-side protected inference boundary for confidential ComputeMesh jobs.

This module contains the content-bearing side of protected execution. It is meant
to run *inside* the attested workload boundary. The gateway never imports it and
never receives plaintext. There is deliberately no simulated attestation fallback.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import threading
from typing import Any, Iterator, Mapping, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from protocol.confidential_envelope import (
    ConfidentialBinding,
    ConfidentialEnvelope,
    ConfidentialEnvelopeError,
    decrypt_in_attested_recipient,
    encrypt_response_in_attested_recipient,
    generate_attested_recipient_keypair,
)
from protocol.confidential_metering import (
    ConfidentialUsageReceipt,
    generate_attested_metering_keypair,
    sign_confidential_usage,
)
from protocol.confidential_request_contract import create_committed_session_attestation_nonce
from protocol.confidential_stream import encrypt_stream_event_in_attested_recipient
from runtime.confidential.replay_store import ConfidentialReplayStore
from services.common.secure_memory import secure_zero_memory


CONFIDENTIAL_PROVISION_CAPABILITY = "confidential_session_provision_v1"
MAX_PROTECTED_SESSION_SECONDS = 300
MAX_ACTIVE_PROTECTED_SESSIONS = 64


class ProtectedWorkerError(RuntimeError):
    pass


class VendorAttestationIssuer(Protocol):
    def issue(self, *, node_id: str, nonce: str) -> Mapping[str, Any]:
        """Return real vendor evidence for this exact nonce.

        Required normalized keys are `technology`, `measurement`,
        `vendor_evidence`, and `debug_disabled`. Production callers must use a
        hardware-backed issuer. This repository intentionally provides no fake
        issuer that can be selected accidentally.
        """


class ProtectedOpenAIBackend(Protocol):
    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def stream(self, request: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class ProtectedWorkerResult:
    response: Any
    usage_receipt: ConfidentialUsageReceipt


@dataclass
class _ProtectedSession:
    account_id: str
    job_id: str
    model_id: str
    privacy_class: str
    operation: str
    max_prompt_tokens: int
    max_completion_tokens: int
    node_id: str
    runtime_digest: str
    attestation_nonce: str
    recipient_private_key: X25519PrivateKey
    recipient_public_key: str
    metering_private_key: Ed25519PrivateKey
    metering_public_key: str
    data_plane_tls_sha256: str
    expires_at: datetime
    claimed_envelope_id: str | None = None

    @property
    def binding(self) -> ConfidentialBinding:
        return ConfidentialBinding(
            account_id=self.account_id,
            job_id=self.job_id,
            node_id=self.node_id,
            attestation_nonce=self.attestation_nonce,
            runtime_digest=self.runtime_digest,
            data_plane_tls_sha256=self.data_plane_tls_sha256,
            privacy_class=self.privacy_class,
            operation=self.operation,
        )


class ProtectedWorkerSessionManager:
    """One-shot, bounded attestation sessions with durable replay tombstones.

    Session private-key objects are retained only while a provisioned request is
    waiting to execute or actively executing. Completed, failed, expired and
    shutdown sessions are removed from manager state immediately. Python's
    cryptography key objects do not expose a portable explicit zeroization API, so
    production key confidentiality still relies on the declared attested process /
    hardware boundary; mutable request plaintext is explicitly zeroized separately.
    """

    def __init__(
        self,
        *,
        node_id: str,
        runtime_digest: str,
        worker_url: str,
        data_plane_tls_sha256: str,
        replay_store: ConfidentialReplayStore,
        backend: ProtectedOpenAIBackend,
        attestation_issuer: VendorAttestationIssuer,
        session_ttl_seconds: int = 120,
        max_active_sessions: int = 1,
    ) -> None:
        if not isinstance(node_id, str) or not node_id or len(node_id) > 256:
            raise ValueError("invalid protected worker node_id")
        if not isinstance(runtime_digest, str) or not runtime_digest or len(runtime_digest) > 512:
            raise ValueError("invalid protected runtime digest")
        if not isinstance(worker_url, str) or not worker_url.startswith("https://"):
            raise ValueError("protected worker URL must use HTTPS")
        if not (
            isinstance(data_plane_tls_sha256, str)
            and data_plane_tls_sha256.startswith("sha256:")
            and len(data_plane_tls_sha256) == 71
        ):
            raise ValueError("invalid protected data-plane TLS fingerprint")
        if not isinstance(session_ttl_seconds, int) or not 1 <= session_ttl_seconds <= MAX_PROTECTED_SESSION_SECONDS:
            raise ValueError("invalid protected session TTL")
        if (
            not isinstance(max_active_sessions, int)
            or isinstance(max_active_sessions, bool)
            or not 1 <= max_active_sessions <= MAX_ACTIVE_PROTECTED_SESSIONS
        ):
            raise ValueError("invalid protected active-session limit")
        self.node_id = node_id
        self.runtime_digest = runtime_digest
        self.worker_url = worker_url
        self.data_plane_tls_sha256 = data_plane_tls_sha256
        self.replay_store = replay_store
        self.backend = backend
        self.attestation_issuer = attestation_issuer
        self.session_ttl_seconds = session_ttl_seconds
        self.max_active_sessions = max_active_sessions
        self._lock = threading.RLock()
        self._sessions: dict[str, _ProtectedSession] = {}
        self._provisioning: set[str] = set()
        self._closed = False

    def _purge_expired_locked(self, now: datetime) -> int:
        expired = [job_id for job_id, state in self._sessions.items() if state.expires_at <= now]
        for job_id in expired:
            self._sessions.pop(job_id, None)
        return len(expired)

    def purge_expired(self, *, now: datetime | None = None) -> int:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        with self._lock:
            return self._purge_expired_locked(instant)

    def active_session_count(self, *, now: datetime | None = None) -> int:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        with self._lock:
            self._purge_expired_locked(instant)
            return len(self._sessions) + len(self._provisioning)

    def close(self) -> None:
        """Prevent new work and release manager references to request-scoped keys."""
        with self._lock:
            self._closed = True
            self._provisioning.clear()
            self._sessions.clear()

    def _reserve_provision_slot(self, job_id: str, now: datetime) -> None:
        with self._lock:
            if self._closed:
                raise ProtectedWorkerError("protected worker session manager is closed")
            self._purge_expired_locked(now)
            if job_id in self._sessions or job_id in self._provisioning:
                raise ProtectedWorkerError("confidential job_id already provisioned")
            if len(self._sessions) + len(self._provisioning) >= self.max_active_sessions:
                raise ProtectedWorkerError("protected worker confidential capacity is exhausted")
            self._provisioning.add(job_id)

    def _release_provision_slot(self, job_id: str) -> None:
        with self._lock:
            self._provisioning.discard(job_id)

    def _install_session(self, state: _ProtectedSession) -> None:
        with self._lock:
            if self._closed:
                raise ProtectedWorkerError("protected worker session manager is closed")
            if state.job_id not in self._provisioning:
                raise ProtectedWorkerError("protected worker provision slot was lost")
            self._provisioning.remove(state.job_id)
            self._sessions[state.job_id] = state

    def _retire(self, state: _ProtectedSession) -> None:
        with self._lock:
            current = self._sessions.get(state.job_id)
            if current is state:
                self._sessions.pop(state.job_id, None)

    def provision(
        self,
        request: Mapping[str, Any],
        *,
        freshness_challenge: bytes,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Generate one fresh TEE key set and vendor-attest its complete contract."""
        expected = {
            "account_id",
            "job_id",
            "model_id",
            "privacy_class",
            "operation",
            "max_prompt_tokens",
            "max_completion_tokens",
        }
        if not isinstance(request, Mapping) or set(request) != expected:
            raise ProtectedWorkerError("invalid confidential provision contract")
        account_id = _text(request.get("account_id"), "account_id", 256)
        job_id = _text(request.get("job_id"), "job_id", 256)
        model_id = _text(request.get("model_id"), "model_id", 512)
        privacy_class = _text(request.get("privacy_class"), "privacy_class", 64)
        operation = _text(request.get("operation"), "operation", 64)
        if privacy_class != "CONFIDENTIAL":
            raise ProtectedWorkerError("protected TEE worker accepts CONFIDENTIAL only")
        if operation != "chat_completion":
            raise ProtectedWorkerError("protected worker supports chat_completion only")
        max_prompt_tokens = _token_limit(request.get("max_prompt_tokens"), "max_prompt_tokens")
        max_completion_tokens = _token_limit(request.get("max_completion_tokens"), "max_completion_tokens")
        if not isinstance(freshness_challenge, bytes) or len(freshness_challenge) < 16:
            raise ProtectedWorkerError("confidential broker freshness challenge is invalid")

        instant = (now or datetime.now(UTC)).astimezone(UTC)
        self._reserve_provision_slot(job_id, instant)
        try:
            expires = instant + timedelta(seconds=self.session_ttl_seconds)
            recipient_private, recipient_public = generate_attested_recipient_keypair()
            metering_private, metering_public = generate_attested_metering_keypair()
            nonce = create_committed_session_attestation_nonce(
                account_id=account_id,
                job_id=job_id,
                model_id=model_id,
                max_prompt_tokens=max_prompt_tokens,
                max_completion_tokens=max_completion_tokens,
                node_id=self.node_id,
                runtime_digest=self.runtime_digest,
                recipient_public_key=recipient_public,
                metering_public_key=metering_public,
                data_plane_tls_sha256=self.data_plane_tls_sha256,
                privacy_class=privacy_class,
                operation=operation,
                entropy=freshness_challenge,
            )
            evidence = self.attestation_issuer.issue(node_id=self.node_id, nonce=nonce)
            if not isinstance(evidence, Mapping):
                raise ProtectedWorkerError("vendor attestation issuer returned invalid evidence")
            technology = _text(evidence.get("technology"), "attestation technology", 128).lower()
            if technology in {"simulated", "simulation", "none", "test", "mock"}:
                raise ProtectedWorkerError("simulated attestation is forbidden for confidential sessions")
            measurement = _text(evidence.get("measurement"), "attestation measurement", 2048)
            vendor_evidence = evidence.get("vendor_evidence")
            if not isinstance(vendor_evidence, (dict, list)) or not vendor_evidence:
                raise ProtectedWorkerError("vendor attestation evidence is missing")
            if evidence.get("debug_disabled") is not True:
                raise ProtectedWorkerError("confidential hardware debug mode is not proven disabled")

            attestation = {
                "schema_version": 1,
                "node_id": self.node_id,
                "technology": technology,
                "measurement": measurement,
                "runtime_digest": self.runtime_digest,
                "ephemeral_public_key": recipient_public,
                "metering_public_key": metering_public,
                "data_plane_tls_sha256": self.data_plane_tls_sha256,
                "nonce": nonce,
                "issued_at": instant.isoformat().replace("+00:00", "Z"),
                "expires_at": expires.isoformat().replace("+00:00", "Z"),
                "debug_disabled": True,
                "account_id": account_id,
                "job_id": job_id,
                "model_id": model_id,
                "max_prompt_tokens": max_prompt_tokens,
                "max_completion_tokens": max_completion_tokens,
                "privacy_class": privacy_class,
                "operation": operation,
                "vendor_evidence": vendor_evidence,
            }
            state = _ProtectedSession(
                account_id=account_id,
                job_id=job_id,
                model_id=model_id,
                privacy_class=privacy_class,
                operation=operation,
                max_prompt_tokens=max_prompt_tokens,
                max_completion_tokens=max_completion_tokens,
                node_id=self.node_id,
                runtime_digest=self.runtime_digest,
                attestation_nonce=nonce,
                recipient_private_key=recipient_private,
                recipient_public_key=recipient_public,
                metering_private_key=metering_private,
                metering_public_key=metering_public,
                data_plane_tls_sha256=self.data_plane_tls_sha256,
                expires_at=expires,
            )
            self._install_session(state)
        except Exception:
            self._release_provision_slot(job_id)
            raise
        return {
            "schema_version": 1,
            "job_id": job_id,
            "account_id": account_id,
            "model_id": model_id,
            "privacy_class": privacy_class,
            "operation": operation,
            "max_prompt_tokens": max_prompt_tokens,
            "max_completion_tokens": max_completion_tokens,
            "expires_at": attestation["expires_at"],
            "endpoint": {
                "url": self.worker_url,
                "node_id": self.node_id,
                "runtime_digest": self.runtime_digest,
                "attestation_nonce": nonce,
                "recipient_public_key": recipient_public,
                "metering_public_key": metering_public,
                "tls_certificate_sha256": self.data_plane_tls_sha256,
            },
            "attestation": attestation,
        }

    def execute(self, envelope: ConfidentialEnvelope | Mapping[str, Any]) -> ProtectedWorkerResult:
        parsed, state = self._claim(envelope)
        try:
            request = self._decrypt_json(parsed, state)
            if request.get("stream", False) is not False:
                raise ProtectedWorkerError("non-stream protected endpoint received stream=true")
            _require_model(request, state.model_id)
            response = self.backend.complete(request)
            if not isinstance(response, Mapping):
                raise ProtectedWorkerError("protected backend returned invalid OpenAI response")
            prompt_tokens, completion_tokens = _usage(response.get("usage"), state)
            encoded = _json_bytes(response)
            protected_response = encrypt_response_in_attested_recipient(
                parsed,
                encoded,
                recipient_private_key=state.recipient_private_key,
            )
            receipt = sign_confidential_usage(
                private_key=state.metering_private_key,
                account_id=state.account_id,
                job_id=state.job_id,
                request_envelope_id=parsed.envelope_id,
                response_id=protected_response.response_id,
                node_id=state.node_id,
                runtime_digest=state.runtime_digest,
                privacy_class=state.privacy_class,
                operation=state.operation,
                model_id=state.model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            return ProtectedWorkerResult(protected_response, receipt)
        finally:
            self._retire(state)

    def stream(self, envelope: ConfidentialEnvelope | Mapping[str, Any]) -> Iterator[ProtectedWorkerResult]:
        parsed, state = self._claim(envelope)
        try:
            request = self._decrypt_json(parsed, state)
            if request.get("stream") is not True:
                raise ProtectedWorkerError("stream protected endpoint requires stream=true")
            _require_model(request, state.model_id)
            sequence = 0
            usage: tuple[int, int] | None = None
            for chunk in self.backend.stream(request):
                if not isinstance(chunk, Mapping):
                    raise ProtectedWorkerError("protected backend returned invalid stream chunk")
                if chunk.get("usage") is not None:
                    usage = _usage(chunk.get("usage"), state)
                protected = encrypt_stream_event_in_attested_recipient(
                    parsed,
                    sequence=sequence,
                    done=False,
                    chunk=chunk,
                    recipient_private_key=state.recipient_private_key,
                )
                sequence += 1
                yield ProtectedWorkerResult(protected, usage_receipt=None)  # type: ignore[arg-type]
            if usage is None:
                raise ProtectedWorkerError("protected streaming backend did not provide trusted usage")
            final_response = encrypt_stream_event_in_attested_recipient(
                parsed,
                sequence=sequence,
                done=True,
                chunk=None,
                recipient_private_key=state.recipient_private_key,
            )
            receipt = sign_confidential_usage(
                private_key=state.metering_private_key,
                account_id=state.account_id,
                job_id=state.job_id,
                request_envelope_id=parsed.envelope_id,
                response_id=final_response.response_id,
                node_id=state.node_id,
                runtime_digest=state.runtime_digest,
                privacy_class=state.privacy_class,
                operation=state.operation,
                model_id=state.model_id,
                prompt_tokens=usage[0],
                completion_tokens=usage[1],
            )
            yield ProtectedWorkerResult(final_response, receipt)
        finally:
            self._retire(state)

    def _claim(
        self,
        envelope: ConfidentialEnvelope | Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> tuple[ConfidentialEnvelope, _ProtectedSession]:
        try:
            parsed = envelope if isinstance(envelope, ConfidentialEnvelope) else ConfidentialEnvelope.from_dict(envelope)
            parsed.validate()
        except (ValueError, ConfidentialEnvelopeError) as exc:
            raise ProtectedWorkerError("invalid confidential envelope") from exc
        with self._lock:
            if self._closed:
                raise ProtectedWorkerError("protected worker session manager is closed")
            state = self._sessions.get(parsed.binding.job_id)
            if state is None:
                raise ProtectedWorkerError("protected session not found or already consumed")
            instant = (now or datetime.now(UTC)).astimezone(UTC)
            if state.expires_at <= instant:
                self._sessions.pop(state.job_id, None)
                raise ProtectedWorkerError("protected session expired")
            if parsed.binding != state.binding:
                raise ProtectedWorkerError("protected envelope does not match attested session")
            if state.claimed_envelope_id is not None:
                raise ProtectedWorkerError("protected session is already consumed")
            # One job/attestation is one execution. Claim before decryption so a
            # backend failure cannot turn retries into oracle/replay behavior.
            state.claimed_envelope_id = parsed.envelope_id
        try:
            self.replay_store.claim(
                parsed,
                expected_account_id=state.account_id,
                expected_privacy_class=state.privacy_class,
                expected_operation=state.operation,
            )
        except Exception:
            self._retire(state)
            raise
        return parsed, state

    @staticmethod
    def _decrypt_json(parsed: ConfidentialEnvelope, state: _ProtectedSession) -> dict[str, Any]:
        plaintext = decrypt_in_attested_recipient(
            parsed,
            recipient_private_key=state.recipient_private_key,
            expected_binding=state.binding,
        )
        try:
            try:
                value = json.loads(bytes(plaintext).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ProtectedWorkerError("protected request plaintext is not JSON") from exc
        finally:
            secure_zero_memory(plaintext)
        if not isinstance(value, dict):
            raise ProtectedWorkerError("protected OpenAI request must be an object")
        return value


def decode_freshness_challenge(value: Any) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ProtectedWorkerError("invalid confidential freshness challenge")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    except (ValueError, UnicodeError) as exc:
        raise ProtectedWorkerError("invalid confidential freshness challenge") from exc
    if len(raw) < 16 or len(raw) > 64:
        raise ProtectedWorkerError("invalid confidential freshness challenge length")
    return raw


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ProtectedWorkerError(f"invalid {name}")
    result = value.strip()
    if not result or len(result) > limit:
        raise ProtectedWorkerError(f"invalid {name}")
    return result


def _token_limit(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1_000_000:
        raise ProtectedWorkerError(f"invalid {name}")
    return value


def _require_model(request: Mapping[str, Any], expected: str) -> None:
    if request.get("model") != expected:
        raise ProtectedWorkerError("protected request model does not match attested session")


def _usage(value: Any, state: _ProtectedSession) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise ProtectedWorkerError("protected backend usage metadata is required")
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    if not isinstance(prompt, int) or isinstance(prompt, bool) or prompt < 0:
        raise ProtectedWorkerError("invalid protected prompt token usage")
    if not isinstance(completion, int) or isinstance(completion, bool) or completion < 0:
        raise ProtectedWorkerError("invalid protected completion token usage")
    if prompt > state.max_prompt_tokens or completion > state.max_completion_tokens:
        raise ProtectedWorkerError("protected backend usage exceeds attested reservation")
    return prompt, completion


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProtectedWorkerError("protected backend returned non-JSON output") from exc
