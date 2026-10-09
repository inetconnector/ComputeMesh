#!/usr/bin/env python3
"""Runnable public ComputeMesh provider agent for the live development path.

The agent connects to the public provider-control listener over verified TLS,
proves the enrolled Ed25519 node identity, publishes an already measured profile,
runtime advertisement and benchmark evidence, then serves authenticated execution-
attestation requests. Optional GPU-promo work is executed only from locally pinned
llama.cpp/model/device configuration. Private scheduler/pricing/reputation logic
never runs here.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import platform
import secrets
import signal
import socket
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlparse

from apps.node.environment import NodeEnvironmentError, NodeEnvironmentExecutor
from apps.node.inference_backend import LocalOpenAIInferenceBackend
from apps.node.model_preparation import (
    AllowlistedModelPreparationExecutor,
    ModelPreparationManifestError,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from protocol.control import CURRENT_PROTOCOL_MINOR, SUPPORTED_PROTOCOL_MAJOR, ControlEnvelope
from protocol.node_identity import (
    AUTH_METHOD,
    create_node_auth_proof,
    key_id_from_public_key,
)
from protocol.node_session import NodeHelloInfo, NodeSessionState, SessionSnapshot
from protocol.session_contracts import SessionMessageContractValidator
from runtime.capacity_guard import LocalCapacityGuard
from runtime.llama.gpu_promo_challenge import (
    GPU_PROMO_CAPABILITY,
    GpuPromoChallengeConfig,
    GpuPromoChallengeRunner,
    build_signed_gpu_promo_proof,
)
from runtime.llama.node_attestation_service import NodeAttestationService
from services.orchestrator.inference_transport import (
    make_inference_request_handler,
    make_inference_stream_handler,
)
from services.orchestrator.persistent_control_channel import (
    PersistentControlChannelError,
    ProviderPersistentClient,
    recv_frame,
    send_frame,
    tls_client_connector,
)
from tools.security.node_key_storage import load_node_private_key

BASE_CAPABILITIES = (
    "execution_attestation_v1",
    "live_runtime_registration_v1",
    "capacity_reservation_v1",
)
MODEL_PREPARATION_CAPABILITY = "model_preparation_v1"
ENVIRONMENT_CAPABILITY = "mesh_environment_v1"


def _accepts_cancel_token(handler: Callable[..., Any] | None) -> bool:
    if handler is None:
        return False
    try:
        parameters = inspect.signature(handler).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [
        parameter for parameter in parameters
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    return len(positional) >= 3 or any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters
    )


class ProviderAgentError(RuntimeError):
    pass


def _optional_path(value: str | os.PathLike[str] | None) -> Path | None:
    """Treat an empty service-manager expansion as an omitted path."""
    if value is None:
        return None
    text = os.fspath(value).strip()
    return Path(text) if text else None


def _install_shutdown_handlers(client: ProviderPersistentClient) -> Callable[[], None]:
    """Make service-manager termination unblock the persistent provider loop."""
    previous: dict[int, Any] = {}

    def request_stop(_signum: int, _frame: Any) -> None:
        client.stop()

    for name in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, name, None)
        if signum is not None:
            previous[signum] = signal.signal(signum, request_stop)

    def restore() -> None:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    return restore


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProviderAgentError(f"required JSON file does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderAgentError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise ProviderAgentError(f"JSON root must be an object: {path}")
    return value


_MODEL_CATALOGUE_KEYS = (
    "status",
    "quantization",
    "size_bytes",
    "parameters",
    "slots",
    "free_vram_bytes",
    "available_vram_bytes",
    "vram_bytes",
    "context_tokens",
    "context_size",
    "max_context_tokens",
    "throughput_tokens_per_second",
)


def _normalize_model_catalogue(raw_models: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Expose only bounded, locally available model metadata to the control plane."""
    normalized: list[dict[str, Any]] = []
    for raw in raw_models:
        if not isinstance(raw, Mapping):
            raise ProviderAgentError("model catalogue contains a non-object")
        available = raw.get("available", raw.get("present", True))
        if available is False:
            continue
        model_id = raw.get("model_id") or raw.get("id") or raw.get("model") or raw.get("name")
        if not isinstance(model_id, str) or not 1 <= len(model_id) <= 256:
            raise ProviderAgentError("model catalogue contains an invalid model_id")
        item: dict[str, Any] = {"model_id": model_id}
        for key in _MODEL_CATALOGUE_KEYS:
            value = raw.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                item[key] = value
        for key in ("capabilities", "modalities"):
            value = raw.get(key)
            if isinstance(value, (list, tuple, set)):
                item[key] = [str(entry)[:128] for entry in list(value)[:32]]
        normalized.append(item)
        if len(normalized) > 512:
            raise ProviderAgentError("model catalogue is too large")
    return tuple(normalized)


def _profile_device_memory_mb(profile: Mapping[str, Any]) -> dict[str, int]:
    """Extract only bounded accelerator memory for local admission checks."""
    raw_devices = profile.get("devices")
    if not isinstance(raw_devices, (list, tuple)):
        return {}
    devices: dict[str, int] = {}
    for raw in raw_devices:
        if not isinstance(raw, Mapping):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in {"gpu", "accelerator", "cuda", "rocm", "metal"}:
            continue
        device_id = str(raw.get("device_id") or "").strip()
        raw_bytes = raw.get("memory_total_bytes")
        if not device_id or isinstance(raw_bytes, bool):
            continue
        try:
            memory_mb = int(raw_bytes) // (1024 * 1024)
        except (TypeError, ValueError):
            continue
        if memory_mb > 0:
            devices[device_id] = memory_mb
    return devices


def _load_local_model_catalogue(path: Path | None) -> tuple[dict[str, Any], ...]:
    if path is not None:
        document = _load_json(path)
        if document.get("schema_version") != 1 or not isinstance(document.get("models"), list):
            raise ProviderAgentError("model catalogue must contain schema_version 1 and a models list")
        return _normalize_model_catalogue(document["models"])
    try:
        from services.appliance_dashboard.model_manager import get_model_manager

        return _normalize_model_catalogue(get_model_manager().list_models())
    except Exception as exc:
        raise ProviderAgentError(f"local model catalogue could not be read: {exc}") from exc


def _managed_model_cancel_callback(endpoint: str) -> Callable[[], None] | None:
    """Return a process-stop hook only for an explicitly owned NodeOS runtime."""
    enabled = os.environ.get("COMPUTEMESH_NODEOS_STOP_MANAGED_MODEL_ON_CANCEL", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None

    from services.appliance_dashboard.model_manager import get_model_manager

    manager = get_model_manager()
    engine = manager.engine
    managed_origin = f"http://{engine.host}:{engine.port}"
    requested = urlparse(endpoint)
    expected = urlparse(managed_origin)
    if (requested.scheme.lower(), requested.netloc.lower()) != (
        expected.scheme.lower(),
        expected.netloc.lower(),
    ):
        raise ProviderAgentError(
            "managed-model cancellation requires the inference endpoint owned by NodeOS model engine"
        )
    return engine.stop


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink() or not path.is_file():
        raise ProviderAgentError("node private key must be an existing non-symlink file")
    try:
        return load_node_private_key(path)
    except Exception as exc:
        raise ProviderAgentError(f"node private key could not be loaded: {exc}") from exc



def _envelope(
    *,
    message_type: str,
    actor_id: str,
    target_id: str,
    revision: int,
    payload: Mapping[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return ControlEnvelope(
        protocol_major=SUPPORTED_PROTOCOL_MAJOR,
        protocol_minor=CURRENT_PROTOCOL_MINOR,
        message_type=message_type,
        request_id="node-" + secrets.token_hex(12),
        correlation_id=correlation_id,
        actor_id=actor_id,
        target_id=target_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        expected_revision=revision,
        payload=dict(payload),
    ).to_dict()


def _send_envelope_and_ack(
    sock: socket.socket,
    *,
    message_type: str,
    actor_id: str,
    target_id: str,
    revision: int,
    payload: Mapping[str, Any],
    correlation_id: str,
) -> tuple[int, str]:
    SessionMessageContractValidator().validate(message_type, payload)
    send_frame(
        sock,
        {
            "kind": "envelope",
            "document": _envelope(
                message_type=message_type,
                actor_id=actor_id,
                target_id=target_id,
                revision=revision,
                payload=payload,
                correlation_id=correlation_id,
            ),
        },
    )
    ack = recv_frame(sock)
    if ack.get("kind") != "session_ack":
        raise ProviderAgentError(f"control plane did not acknowledge {message_type}")
    ack_revision = ack.get("revision")
    state = ack.get("state")
    if isinstance(ack_revision, bool) or not isinstance(ack_revision, int) or ack_revision < revision:
        raise ProviderAgentError(f"invalid revision acknowledgement for {message_type}")
    if not isinstance(state, str) or not state:
        raise ProviderAgentError(f"invalid state acknowledgement for {message_type}")
    return ack_revision, state


class ProviderAgent:
    def __init__(
        self,
        *,
        node_id: str,
        private_key_path: Path,
        profile: dict[str, Any],
        prefill: dict[str, Any],
        decode: dict[str, Any],
        runtime_advertisement: dict[str, Any],
        models: Iterable[Mapping[str, Any]] = (),
        network_reports: Sequence[dict[str, Any]] = (),
        capacity_guard: LocalCapacityGuard | None = None,
        gpu_promo_runner: GpuPromoChallengeRunner | None = None,
        inference_executor: Callable[[SessionSnapshot, Mapping[str, Any]], Mapping[str, Any]] | None = None,
        inference_stream_executor: Callable[[SessionSnapshot, Mapping[str, Any]], Iterable[Mapping[str, Any]]] | None = None,
        model_preparation_executor: Callable[[SessionSnapshot, Mapping[str, Any]], Mapping[str, Any]] | None = None,
        environment_executor: Callable[[SessionSnapshot, Mapping[str, Any]], Mapping[str, Any]] | None = None,
        enforce_inference_capacity: bool = False,
    ) -> None:
        if not node_id or len(node_id) > 128:
            raise ValueError("invalid node_id")
        self.node_id = node_id
        self.private_key_path = private_key_path
        self.private_key = _load_private_key(private_key_path)
        self.profile = dict(profile)
        self.prefill = dict(prefill)
        self.decode = dict(decode)
        self.runtime_advertisement = dict(runtime_advertisement)
        self.models = _normalize_model_catalogue(models)
        self.network_reports = tuple(dict(item) for item in network_reports)
        self.capacity_guard = capacity_guard or LocalCapacityGuard(
            node_id=node_id,
            device_memory_mb=_profile_device_memory_mb(self.profile),
        )
        self.gpu_promo_runner = gpu_promo_runner
        self.inference_executor = inference_executor
        self.inference_stream_executor = inference_stream_executor
        self.model_preparation_executor = model_preparation_executor
        self.environment_executor = environment_executor
        self.enforce_inference_capacity = bool(enforce_inference_capacity)
        self._inference_handler = (
            make_inference_request_handler(inference_executor)
            if inference_executor is not None
            else None
        )
        self._inference_stream_handler = (
            make_inference_stream_handler(inference_stream_executor)
            if inference_stream_executor is not None
            else None
        )
        self.capabilities = BASE_CAPABILITIES + ((GPU_PROMO_CAPABILITY,) if gpu_promo_runner else ())
        if inference_executor is not None:
            self.capabilities += ("inference_v1",)
        if inference_stream_executor is not None:
            self.capabilities += ("inference_stream_v1",)
        if model_preparation_executor is not None:
            self.capabilities += (MODEL_PREPARATION_CAPABILITY,)
        if environment_executor is not None:
            self.capabilities += (ENVIRONMENT_CAPABILITY,)
        if self.profile.get("node_id") != node_id:
            raise ProviderAgentError("profile node_id does not match configured node identity")
        revision = self.profile.get("profile_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ProviderAgentError("profile_revision must be a positive integer")
        for document in (self.prefill, self.decode):
            if document.get("profile_revision") != revision:
                raise ProviderAgentError("benchmark profile_revision does not match node profile")
        if self.runtime_advertisement.get("node_id") != node_id:
            raise ProviderAgentError("runtime advertisement node_id mismatch")
        if self.runtime_advertisement.get("profile_revision") != revision:
            raise ProviderAgentError("runtime advertisement profile_revision mismatch")
        contracts = SessionMessageContractValidator()
        contracts.validate("NodeProfileUpdate", self.profile)
        contracts.validate(
            "ModelCatalogueUpdate",
            {
                "schema_version": 1,
                "node_id": node_id,
                "profile_revision": revision,
                "models": list(self.models),
            },
        )
        contracts.validate("RuntimeAdvertisement", self.runtime_advertisement)
        contracts.validate("BenchmarkReport", self.prefill)
        contracts.validate("BenchmarkReport", self.decode)
        for report in self.network_reports:
            contracts.validate("BenchmarkReport", report)
        if self.prefill.get("benchmark_name") != "llama_cpp_prefill":
            raise ProviderAgentError("prefill evidence must use llama_cpp_prefill")
        if self.decode.get("benchmark_name") != "llama_cpp_decode":
            raise ProviderAgentError("decode evidence must use llama_cpp_decode")
        self.attestation = NodeAttestationService(
            node_id=node_id,
            private_key_path=private_key_path,
        )

    @property
    def key_id(self) -> str:
        raw = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return key_id_from_public_key(raw)

    def handshake(self, sock: socket.socket, challenge: dict[str, Any]) -> SessionSnapshot:
        session_id = challenge.get("session_id")
        nonce = challenge.get("challenge")
        control_plane_id = challenge.get("control_plane_id")
        if not all(isinstance(item, str) and item for item in (session_id, nonce, control_plane_id)):
            raise ProviderAgentError("control-plane challenge is incomplete")

        hello_payload = {
            "protocol_major": SUPPORTED_PROTOCOL_MAJOR,
            "protocol_minor": CURRENT_PROTOCOL_MINOR,
            "agent_version": "computemesh-provider/0.1",
            "platform": f"{platform.system()}-{platform.machine()}",
            "node_id": self.node_id,
            "supported_auth_methods": [AUTH_METHOD],
            "capabilities": list(self.capabilities),
        }
        revision, _ = _send_envelope_and_ack(
            sock,
            message_type="NodeHello",
            actor_id=self.node_id,
            target_id=control_plane_id,
            revision=0,
            payload=hello_payload,
            correlation_id=session_id,
        )
        hello = NodeHelloInfo(
            agent_version=str(hello_payload["agent_version"]),
            platform=str(hello_payload["platform"]),
            supported_auth_methods=tuple(hello_payload["supported_auth_methods"]),
            capabilities=frozenset(hello_payload["capabilities"]),
            node_id=self.node_id,
            protocol_major=SUPPORTED_PROTOCOL_MAJOR,
            protocol_minor=CURRENT_PROTOCOL_MINOR,
        )
        credential = create_node_auth_proof(
            private_key=self.private_key,
            node_id=self.node_id,
            key_id=self.key_id,
            session_id=session_id,
            challenge=nonce,
            hello=hello,
        )
        revision, _ = _send_envelope_and_ack(
            sock,
            message_type="NodeAuthenticate",
            actor_id=self.node_id,
            target_id=control_plane_id,
            revision=revision,
            payload={"method": AUTH_METHOD, "credential": credential},
            correlation_id=session_id,
        )
        revision, _ = _send_envelope_and_ack(
            sock,
            message_type="CapabilityNegotiation",
            actor_id=self.node_id,
            target_id=control_plane_id,
            revision=revision,
            payload={"accepted_capabilities": list(self.capabilities)},
            correlation_id=session_id,
        )
        revision, state = _send_envelope_and_ack(
            sock,
            message_type="NodeProfileUpdate",
            actor_id=self.node_id,
            target_id=control_plane_id,
            revision=revision,
            payload=self.profile,
            correlation_id=session_id,
        )
        revision, state = _send_envelope_and_ack(
            sock,
            message_type="ModelCatalogueUpdate",
            actor_id=self.node_id,
            target_id=control_plane_id,
            revision=revision,
            payload={
                "schema_version": 1,
                "node_id": self.node_id,
                "profile_revision": self.profile["profile_revision"],
                "models": list(self.models),
            },
            correlation_id=session_id,
        )
        for message_type, document in (
            ("RuntimeAdvertisement", self.runtime_advertisement),
            ("BenchmarkReport", self.prefill),
            ("BenchmarkReport", self.decode),
        ):
            revision, state = _send_envelope_and_ack(
                sock,
                message_type=message_type,
                actor_id=self.node_id,
                target_id=control_plane_id,
                revision=revision,
                payload=document,
                correlation_id=session_id,
            )
        for report in self.network_reports:
            revision, state = _send_envelope_and_ack(
                sock,
                message_type="BenchmarkReport",
                actor_id=self.node_id,
                target_id=control_plane_id,
                revision=revision,
                payload=report,
                correlation_id=session_id,
            )
        try:
            parsed_state = NodeSessionState(state)
        except ValueError as exc:
            raise ProviderAgentError(f"unknown acknowledged node-session state {state!r}") from exc
        return SessionSnapshot(
            session_id=session_id,
            state=parsed_state,
            revision=revision,
            protocol_major=SUPPORTED_PROTOCOL_MAJOR,
            protocol_minor=CURRENT_PROTOCOL_MINOR,
            node_id=self.node_id,
            principal_id="provider-local",
            auth_method=AUTH_METHOD,
            credential_expires_at=datetime.now(UTC) + timedelta(minutes=15),
            negotiated_capabilities=frozenset(self.capabilities),
            profile_revision=int(self.profile["profile_revision"]),
            drain_reason=None,
            close_reason=None,
            key_id=self.key_id,
        )

    def _handle_gpu_promo_request(
        self,
        payload: dict[str, Any],
        session: SessionSnapshot,
    ) -> dict[str, Any]:
        if self.gpu_promo_runner is None or GPU_PROMO_CAPABILITY not in session.negotiated_capabilities:
            raise ProviderAgentError("GPU promo challenge capability is not enabled")
        contracts = SessionMessageContractValidator()
        contracts.validate("GpuPromoChallengeRequest", payload)
        if payload.get("session_id") != session.session_id:
            raise ProviderAgentError("GPU promo request session id mismatch")
        if payload.get("session_revision") != session.revision:
            raise ProviderAgentError("GPU promo request session revision mismatch")
        challenge = payload.get("challenge")
        if not isinstance(challenge, dict):
            raise ProviderAgentError("GPU promo challenge is missing")
        if challenge.get("node_id") != self.node_id:
            raise ProviderAgentError("GPU promo challenge targets another node")
        if challenge.get("key_id") != self.key_id:
            raise ProviderAgentError("GPU promo challenge targets another node key")

        result = self.gpu_promo_runner.run(challenge)
        proof = build_signed_gpu_promo_proof(
            challenge=challenge,
            result=result,
            private_key=self.private_key,
        )
        response = {
            "session_id": session.session_id,
            "session_revision": session.revision,
            "node_id": self.node_id,
            "key_id": self.key_id,
            "proof": proof,
        }
        contracts.validate("GpuPromoChallengeResponse", response)
        return response

    def handle_request(
        self,
        message_type: str,
        payload: dict[str, Any],
        session: SessionSnapshot,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if message_type == "EnvironmentRequest":
            if self.environment_executor is None:
                raise ProviderAgentError("mesh environment runtime is not configured on this node")
            contracts = SessionMessageContractValidator()
            contracts.validate(message_type, payload)
            if (
                payload.get("session_id") != session.session_id
                or payload.get("session_revision") != session.revision
                or payload.get("node_id") != self.node_id
            ):
                raise ProviderAgentError("environment request session or node binding mismatch")
            try:
                if cancel_event is not None and _accepts_cancel_token(self.environment_executor):
                    raw_response = self.environment_executor(session, payload, cancel_event)
                else:
                    raw_response = self.environment_executor(session, payload)
            except Exception as exc:
                raise ProviderAgentError("environment executor failed") from exc
            if not isinstance(raw_response, Mapping):
                raise ProviderAgentError("environment executor returned a non-object response")
            response = {
                "schema_version": 1,
                "session_id": session.session_id,
                "session_revision": session.revision,
                "node_id": self.node_id,
                "environment_id": payload["environment_id"],
                "operation": payload["operation"],
                "status": raw_response.get("status", "ok"),
            }
            for key in ("lease_id", "issued_at", "expires_at", "lease_revision", "result", "reason_code"):
                if key in raw_response:
                    response[key] = raw_response[key]
            contracts.validate("EnvironmentResponse", response)
            return response
        if message_type == "ModelPreparationRequest":
            if self.model_preparation_executor is None:
                raise ProviderAgentError("model preparation runtime is not configured on this node")
            contracts = SessionMessageContractValidator()
            contracts.validate(message_type, payload)
            if (
                payload.get("session_id") != session.session_id
                or payload.get("session_revision") != session.revision
                or payload.get("node_id") != self.node_id
            ):
                raise ProviderAgentError("model preparation request session or node binding mismatch")
            try:
                raw_response = self.model_preparation_executor(session, payload)
            except Exception as exc:
                raise ProviderAgentError("model preparation executor failed") from exc
            if not isinstance(raw_response, Mapping):
                raise ProviderAgentError("model preparation executor returned a non-object response")
            response = {
                "schema_version": 1,
                "session_id": session.session_id,
                "session_revision": session.revision,
                "node_id": self.node_id,
                "model_id": payload["model_id"],
                "artifact_digest": payload["artifact_digest"],
                "status": raw_response.get("status", "prepared"),
            }
            for key in ("reason_code", "idempotency_replay"):
                if key in raw_response:
                    response[key] = raw_response[key]
            contracts.validate("ModelPreparationResponse", response)
            return response
        if message_type == "InferenceRequest":
            if self._inference_handler is None:
                raise ProviderAgentError("inference runtime is not configured on this node")
            self._require_inference_capacity(payload)
            try:
                return self._inference_handler(message_type, payload, session, cancel_event)
            except Exception as exc:
                if isinstance(exc, ProviderAgentError):
                    raise
                raise ProviderAgentError(str(exc)) from exc
        if message_type == "CapacityReserveRequest":
            SessionMessageContractValidator().validate(message_type, payload)
            reservation = self.capacity_guard.acquire(
                job_id=str(payload["job_id"]),
                lease_id=str(payload["lease_id"]),
                memory_mb=int(payload["memory_mb"]),
                ttl_seconds=int(payload["ttl_seconds"]),
                device_id=str(payload["device_id"]),
            )
            return {
                "node_id": self.node_id,
                "job_id": reservation.job_id,
                "lease_id": reservation.lease_id,
                "reservation_id": reservation.reservation_id,
                "device_id": reservation.device_id,
                "expires_at": reservation.expires_at.isoformat().replace("+00:00", "Z"),
            }
        if message_type == "CapacityReleaseRequest":
            SessionMessageContractValidator().validate(message_type, payload)
            released = self.capacity_guard.release(
                str(payload["job_id"]), lease_id=str(payload["lease_id"])
            )
            return {"node_id": self.node_id, "job_id": str(payload["job_id"]), "released": released}
        if message_type == "GpuPromoChallengeRequest":
            return self._handle_gpu_promo_request(payload, session)
        if message_type != "ExecutionAttestationRequest":
            raise ProviderAgentError(f"unsupported control-plane request: {message_type}")
        SessionMessageContractValidator().validate(message_type, payload)
        request = payload.get("request")
        request_session_id = payload.get("session_id")
        request_revision = payload.get("session_revision")
        if not isinstance(request, dict) or request_revision != session.revision:
            raise ProviderAgentError("attestation request session revision mismatch")
        return self.attestation.handle(
            authenticated_node_id=self.node_id,
            session_id=session.session_id,
            request_session_id=str(request_session_id),
            request_document=request,
        )

    def _require_inference_capacity(self, payload: Mapping[str, Any]) -> None:
        if not self.enforce_inference_capacity:
            return
        lease_id = str(payload.get("lease_id") or "")
        try:
            self.capacity_guard.require_active_lease(lease_id)
        except Exception as exc:
            raise ProviderAgentError("inference requires an active provider capacity reservation") from exc

    def handle_stream_request(
        self,
        message_type: str,
        payload: dict[str, Any],
        session: SessionSnapshot,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        if self._inference_stream_handler is None:
            raise ProviderAgentError("inference streaming runtime is not configured on this node")
        self._require_inference_capacity(payload)
        return self._inference_stream_handler(message_type, payload, session, cancel_event)


def _runtime_document(
    *,
    node_id: str,
    profile_revision: int,
    rpc_host: str,
    rpc_port: int,
    build_number: int,
    build_commit: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "node_id": node_id,
        "profile_revision": profile_revision,
        "runtime": "llama.cpp",
        "llama_build_commit": build_commit,
        "llama_build_number": build_number,
        "rpc": {"host": rpc_host, "port": rpc_port},
    }


def _gpu_promo_runner_from_args(args: argparse.Namespace) -> GpuPromoChallengeRunner | None:
    values = (
        args.promo_llama_server,
        args.promo_model,
        args.promo_device,
        args.promo_accelerator_id,
    )
    configured = tuple(value is not None for value in values)
    if any(configured) and not all(configured):
        raise ProviderAgentError(
            "GPU promo requires --promo-llama-server, --promo-model, --promo-device and "
            "--promo-accelerator-id together"
        )
    if not any(configured):
        return None
    config = GpuPromoChallengeConfig(
        llama_server=args.promo_llama_server,
        model=args.promo_model,
        device=args.promo_device,
        accelerator_id=args.promo_accelerator_id,
        local_port=args.promo_port,
        context_size=args.promo_ctx_size,
        max_timeout_seconds=args.promo_max_timeout,
    )
    return GpuPromoChallengeRunner(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a real ComputeMesh live provider agent")
    parser.add_argument("--control-host", required=True)
    parser.add_argument("--control-port", type=int, default=7443)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--server-hostname")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--prefill", type=Path, required=True)
    parser.add_argument("--decode", type=Path, required=True)
    parser.add_argument(
        "--model-catalogue",
        type=_optional_path,
        help="optional signed/operator-generated model inventory; otherwise read the local NodeOS catalogue",
        default=_optional_path(os.environ.get("COMPUTEMESH_MODEL_CATALOGUE")),
    )
    parser.add_argument("--network-report", type=Path, action="append", default=[])
    parser.add_argument("--rpc-host", required=True)
    parser.add_argument("--rpc-port", type=int, default=50052)
    parser.add_argument("--llama-build-number", type=int, required=True)
    parser.add_argument("--llama-build-commit", required=True)
    parser.add_argument("--promo-llama-server", type=Path)
    parser.add_argument("--promo-model", type=Path)
    parser.add_argument("--promo-device")
    parser.add_argument("--promo-accelerator-id")
    parser.add_argument("--promo-port", type=int, default=18090)
    parser.add_argument("--promo-ctx-size", type=int, default=2048)
    parser.add_argument("--promo-max-timeout", type=float, default=300.0)
    parser.add_argument(
        "--inference-endpoint",
        help="optional loopback OpenAI-compatible NodeOS endpoint; enables inference_v1",
        default=os.environ.get("COMPUTEMESH_NODEOS_INFERENCE_ENDPOINT"),
    )
    parser.add_argument(
        "--inference-auth-token",
        help="optional local-only bearer token for the loopback inference endpoint",
        default=os.environ.get("COMPUTEMESH_NODEOS_INFERENCE_AUTH_TOKEN"),
    )
    parser.add_argument(
        "--model-preparation-manifest",
        type=_optional_path,
        help="optional local allowlist for authenticated model preparation",
        default=_optional_path(os.environ.get("COMPUTEMESH_MODEL_PREPARATION_MANIFEST")),
    )
    parser.add_argument(
        "--environment-root",
        type=_optional_path,
        help="optional persistent root for typed mesh environments; enables mesh_environment_v1",
        default=_optional_path(os.environ.get("COMPUTEMESH_NODEOS_ENVIRONMENT_ROOT")),
    )
    args = parser.parse_args(argv)

    profile = _load_json(args.profile)
    profile_revision = profile.get("profile_revision")
    if isinstance(profile_revision, bool) or not isinstance(profile_revision, int):
        raise ProviderAgentError("profile lacks integer profile_revision")
    models = _load_local_model_catalogue(args.model_catalogue)
    inference_backend = (
        LocalOpenAIInferenceBackend(
            endpoint=str(args.inference_endpoint),
            auth_token=args.inference_auth_token,
            on_cancel=_managed_model_cancel_callback(str(args.inference_endpoint)),
        )
        if args.inference_endpoint
        else None
    )
    model_preparation_executor = None
    if args.model_preparation_manifest is not None:
        try:
            model_preparation_executor = AllowlistedModelPreparationExecutor.from_path(
                args.model_preparation_manifest
            )
        except ModelPreparationManifestError as exc:
            raise ProviderAgentError(str(exc)) from exc
    environment_executor = None
    if args.environment_root is not None:
        try:
            environment_executor = NodeEnvironmentExecutor(
                node_id=args.node_id,
                root=str(args.environment_root),
                inference_executor=inference_backend,
            )
        except (OSError, ValueError, NodeEnvironmentError) as exc:
            raise ProviderAgentError(str(exc)) from exc
    agent = ProviderAgent(
        node_id=args.node_id,
        private_key_path=args.private_key,
        profile=profile,
        prefill=_load_json(args.prefill),
        decode=_load_json(args.decode),
        runtime_advertisement=_runtime_document(
            node_id=args.node_id,
            profile_revision=profile_revision,
            rpc_host=args.rpc_host,
            rpc_port=args.rpc_port,
            build_number=args.llama_build_number,
            build_commit=args.llama_build_commit,
        ),
        models=models,
        network_reports=tuple(_load_json(path) for path in args.network_report),
        gpu_promo_runner=_gpu_promo_runner_from_args(args),
        inference_executor=inference_backend,
        inference_stream_executor=(inference_backend.stream if inference_backend is not None else None),
        model_preparation_executor=model_preparation_executor,
        environment_executor=environment_executor,
        enforce_inference_capacity=True,
    )
    if not args.ca_file.is_file():
        raise ProviderAgentError("control-plane CA file does not exist")
    connector = tls_client_connector(
        host=args.control_host,
        port=args.control_port,
        ca_file=str(args.ca_file),
        server_hostname=args.server_hostname,
    )
    client = ProviderPersistentClient(
        connector=connector,
        handshake=agent.handshake,
        request_handler=agent.handle_request,
        stream_handler=agent.handle_stream_request,
    )
    restore_shutdown_handlers = _install_shutdown_handlers(client)
    try:
        client.serve_forever()
    except KeyboardInterrupt:
        client.stop()
    except PersistentControlChannelError as exc:
        raise ProviderAgentError(str(exc)) from exc
    finally:
        restore_shutdown_handlers()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderAgentError as exc:
        print(f"provider agent failed: {exc}")
        raise SystemExit(2) from exc
