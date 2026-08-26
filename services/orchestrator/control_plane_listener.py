"""TLS listener for persistent provider control channels."""
from __future__ import annotations

import socket
import ssl
import threading
from typing import Callable

from protocol.node_identity import Ed25519ChallengeVerifier
from protocol.session_wire import BenchmarkAcceptancePolicy
from services.orchestrator.persistent_control_channel import (
    AcceptedProviderSession,
    PersistentNodeControlClient,
    accept_authenticated_provider,
)


class PersistentControlPlaneListener:
    """Accept TLS-encrypted provider sockets and authenticate nodes at the application layer."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        cert_file: str,
        key_file: str,
        verifier: Ed25519ChallengeVerifier,
        benchmark_policy: BenchmarkAcceptancePolicy,
        control_plane_id: str = "computemesh-control-plane",
        capabilities: tuple[str, ...] = ("execution_attestation_v1",),
        on_session: Callable[[AcceptedProviderSession], None] | None = None,
        heartbeat_interval_seconds: float = 15.0,
        stale_after_seconds: float = 45.0,
    ) -> None:
        if heartbeat_interval_seconds <= 0 or stale_after_seconds <= heartbeat_interval_seconds:
            raise ValueError("heartbeat/stale intervals are invalid")
        self.host = host
        self.port = port
        self.verifier = verifier
        self.benchmark_policy = benchmark_policy
        self.control_plane_id = control_plane_id
        self.capabilities = capabilities
        self.on_session = on_session
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.stale_after_seconds = stale_after_seconds
        self.client = PersistentNodeControlClient()
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        self._stop = threading.Event()
        self._listener: socket.socket | None = None
        self._threads: list[threading.Thread] = []

    @property
    def bound_port(self) -> int:
        if self._listener is None:
            return self.port
        return int(self._listener.getsockname()[1])

    def start(self) -> None:
        if self._listener is not None:
            raise RuntimeError("control-plane listener already started")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(64)
        listener.settimeout(1.0)
        self._listener = listener
        accept_thread = threading.Thread(target=self._accept_loop, name="cm-control-accept", daemon=True)
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="cm-control-heartbeat", daemon=True)
        self._threads.extend((accept_thread, heartbeat_thread))
        accept_thread.start()
        heartbeat_thread.start()

    def close(self) -> None:
        self._stop.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                raw, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(target=self._authenticate_socket, args=(raw,), daemon=True)
            self._threads.append(thread)
            thread.start()

    def _authenticate_socket(self, raw: socket.socket) -> None:
        wrapped: ssl.SSLSocket | None = None
        transferred = False
        try:
            wrapped = self._context.wrap_socket(raw, server_side=True)
            accepted = accept_authenticated_provider(
                sock=wrapped,
                verifier=self.verifier,
                benchmark_policy=self.benchmark_policy,
                control_client=self.client,
                control_plane_id=self.control_plane_id,
                control_plane_capabilities=self.capabilities,
            )
            transferred = True
            if self.on_session is not None:
                self.on_session(accepted)
        except Exception:
            pass
        finally:
            if not transferred:
                try:
                    (wrapped or raw).close()
                except OSError:
                    pass

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_interval_seconds):
            self.client.heartbeat_once(stale_after_seconds=self.stale_after_seconds)
