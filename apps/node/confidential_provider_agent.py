#!/usr/bin/env python3
"""Runnable provider agent with a real fail-closed confidential worker boundary.

This process must itself run inside the workload boundary covered by the configured
hardware attestation issuer. It starts the TLS 1.3 ciphertext data plane and reuses
the ordinary Ed25519-authenticated persistent provider-control session for fresh
session provisioning. There is no software/simulated-attestation mode.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from apps.node.provider_agent import (
    ProviderAgent,
    ProviderAgentError,
    _gpu_promo_runner_from_args,
    _load_json,
    _runtime_document,
)
from runtime.confidential.openai_backend import LoopbackOpenAIBackend
from runtime.confidential.protected_worker import (
    CONFIDENTIAL_PROVISION_CAPABILITY,
    ProtectedWorkerSessionManager,
)
from runtime.confidential.provider_control import (
    CONFIDENTIAL_PROVISION_MESSAGE,
    handle_confidential_provision_request,
)
from runtime.confidential.replay_store import SQLiteConfidentialReplayStore
from runtime.confidential.worker_http import ProtectedWorkerHttpService
from services.attestation.vendor_evidence_issuer import PinnedVendorEvidenceIssuer
from services.orchestrator.persistent_control_channel import (
    PersistentControlChannelError,
    ProviderPersistentClient,
    tls_client_connector,
)


class ConfidentialProviderAgent(ProviderAgent):
    def __init__(self, *, protected_manager: ProtectedWorkerSessionManager, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if protected_manager.node_id != self.node_id:
            raise ProviderAgentError("protected worker node identity mismatch")
        self.protected_manager = protected_manager
        self.capabilities = tuple(dict.fromkeys(self.capabilities + (CONFIDENTIAL_PROVISION_CAPABILITY,)))

    def handle_request(self, message_type: str, payload: dict[str, Any], session):
        if message_type == CONFIDENTIAL_PROVISION_MESSAGE:
            return handle_confidential_provision_request(
                payload=payload,
                session=session,
                manager=self.protected_manager,
            )
        return super().handle_request(message_type, payload, session)


def _tls_leaf_sha256(cert_file: Path) -> str:
    if cert_file.is_symlink() or not cert_file.is_file():
        raise ProviderAgentError("protected worker TLS certificate must be a regular non-symlink file")
    try:
        certificate = x509.load_pem_x509_certificate(cert_file.read_bytes())
    except (OSError, ValueError) as exc:
        raise ProviderAgentError("protected worker TLS certificate could not be parsed") from exc
    der = certificate.public_bytes(serialization.Encoding.DER)
    return "sha256:" + hashlib.sha256(der).hexdigest()


def _validate_worker_url(value: str) -> tuple[str, int, str]:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.path or parsed.path == "/":
        raise ProviderAgentError("protected worker URL must be an HTTPS URL with an execution path")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderAgentError("protected worker URL contains forbidden components")
    return parsed.hostname, parsed.port or 443, parsed.path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a confidential ComputeMesh provider agent")
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
    parser.add_argument("--promo-llama-server", type=Path)
    parser.add_argument("--promo-model", type=Path)
    parser.add_argument("--promo-device")
    parser.add_argument("--promo-accelerator-id")
    parser.add_argument("--promo-port", type=int, default=18090)
    parser.add_argument("--promo-ctx-size", type=int, default=2048)
    parser.add_argument("--promo-max-timeout", type=float, default=300.0)

    parser.add_argument("--protected-worker-url", required=True)
    parser.add_argument("--protected-bind-host", required=True)
    parser.add_argument("--protected-bind-port", type=int, required=True)
    parser.add_argument("--protected-tls-cert", type=Path, required=True)
    parser.add_argument("--protected-tls-key", type=Path, required=True)
    parser.add_argument("--protected-runtime-digest", required=True)
    parser.add_argument("--protected-state-dir", type=Path, required=True)
    parser.add_argument("--protected-openai-backend", required=True)
    parser.add_argument("--protected-backend-timeout", type=float, default=120.0)
    parser.add_argument("--protected-session-ttl", type=int, default=120)
    parser.add_argument("--protected-max-active-sessions", type=int, default=1)
    parser.add_argument("--attestation-issuer-executable", type=Path, required=True)
    parser.add_argument("--attestation-issuer-sha256", required=True)
    parser.add_argument("--attestation-issuer-timeout", type=float, default=15.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _url_host, _url_port, execution_path = _validate_worker_url(args.protected_worker_url)
    if not 1 <= args.protected_bind_port <= 65535:
        raise ProviderAgentError("protected worker bind port must be 1..65535")
    if args.protected_state_dir.is_symlink():
        raise ProviderAgentError("protected state directory must not be a symlink")
    args.protected_state_dir.mkdir(parents=True, exist_ok=True)
    if not args.protected_state_dir.is_dir():
        raise ProviderAgentError("protected state directory is unavailable")
    if not args.protected_tls_key.is_file() or args.protected_tls_key.is_symlink():
        raise ProviderAgentError("protected TLS key must be a regular non-symlink file")

    profile = _load_json(args.profile)
    profile_revision = profile.get("profile_revision")
    if isinstance(profile_revision, bool) or not isinstance(profile_revision, int):
        raise ProviderAgentError("profile lacks integer profile_revision")

    try:
        issuer = PinnedVendorEvidenceIssuer(
            executable=args.attestation_issuer_executable,
            sha256=args.attestation_issuer_sha256,
            timeout_seconds=args.attestation_issuer_timeout,
        )
        backend = LoopbackOpenAIBackend(
            args.protected_openai_backend,
            timeout_seconds=args.protected_backend_timeout,
        )
        replay_store = SQLiteConfidentialReplayStore(args.protected_state_dir / "replay.sqlite3")
        manager = ProtectedWorkerSessionManager(
            node_id=args.node_id,
            runtime_digest=args.protected_runtime_digest,
            worker_url=args.protected_worker_url,
            data_plane_tls_sha256=_tls_leaf_sha256(args.protected_tls_cert),
            replay_store=replay_store,
            backend=backend,
            attestation_issuer=issuer,
            session_ttl_seconds=args.protected_session_ttl,
            max_active_sessions=args.protected_max_active_sessions,
        )
        worker_service = ProtectedWorkerHttpService(
            manager=manager,
            bind_host=args.protected_bind_host,
            bind_port=args.protected_bind_port,
            cert_file=args.protected_tls_cert,
            key_file=args.protected_tls_key,
            execution_path=execution_path,
        )
        agent = ConfidentialProviderAgent(
            protected_manager=manager,
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
            gpu_promo_runner=_gpu_promo_runner_from_args(args),
        )
    except (ValueError, OSError) as exc:
        raise ProviderAgentError(f"confidential provider configuration failed: {exc}") from exc

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
    worker_service.start()
    try:
        client.serve_forever()
    except KeyboardInterrupt:
        client.stop()
    except PersistentControlChannelError as exc:
        raise ProviderAgentError(str(exc)) from exc
    finally:
        worker_service.close()
        manager.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderAgentError as exc:
        print(f"confidential provider agent failed: {exc}")
        raise SystemExit(2) from exc
