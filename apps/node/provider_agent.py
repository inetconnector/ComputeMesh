#!/usr/bin/env python3
"""Runnable public ComputeMesh provider agent for the live development path.

The agent connects to the public provider-control listener over verified TLS,
proves the enrolled Ed25519 node identity, publishes an already measured profile,
runtime advertisement and benchmark evidence, then serves authenticated execution-
attestation requests. Private scheduler/pricing/reputation logic never runs here.
"""
from __future__ import annotations

import argparse
import json
import platform
import secrets
import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

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
from runtime.llama.node_attestation_service import NodeAttestationService
from services.orchestrator.persistent_control_channel import (
    ProviderPersistentClient,
    PersistentControlChannelError,
    recv_frame,
    send_frame,
    tls_client_connector,
)

CAPABILITIES = ("execution_attestation_v1", "live_runtime_registration_v1")


class ProviderAgentError(RuntimeError):
    pass


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


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink() or not path.is_file():
        raise ProviderAgentError("node private key must be an existing non-symlink file")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise ProviderAgentError("node private key is not a readable unencrypted PEM key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ProviderAgentError("node private key must be Ed25519")
    return key


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
        network_reports: Sequence[dict[str, Any]] = (),
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
        self.network_reports = tuple(dict(item) for item in network_reports)
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
            "capabilities": list(CAPABILITIES),
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
            payload={"accepted_capabilities": list(CAPABILITIES)},
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
            negotiated_capabilities=frozenset(CAPABILITIES),
            profile_revision=int(self.profile["profile_revision"]),
            drain_reason=None,
            close_reason=None,
        )

    def handle_request(
        self,
        message_type: str,
        payload: dict[str, Any],
        session: SessionSnapshot,
    ) -> dict[str, Any]:
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
    parser.add_argument("--network-report", type=Path, action="append", default=[])
    parser.add_argument("--rpc-host", required=True)
    parser.add_argument("--rpc-port", type=int, default=50052)
    parser.add_argument("--llama-build-number", type=int, required=True)
    parser.add_argument("--llama-build-commit", required=True)
    args = parser.parse_args(argv)

    profile = _load_json(args.profile)
    profile_revision = profile.get("profile_revision")
    if isinstance(profile_revision, bool) or not isinstance(profile_revision, int):
        raise ProviderAgentError("profile lacks integer profile_revision")
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
        network_reports=tuple(_load_json(path) for path in args.network_report),
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
    )
    try:
        client.serve_forever()
    except KeyboardInterrupt:
        client.stop()
    except PersistentControlChannelError as exc:
        raise ProviderAgentError(str(exc)) from exc
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderAgentError as exc:
        print(f"provider agent failed: {exc}")
        raise SystemExit(2) from exc
