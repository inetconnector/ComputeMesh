"""Integrated persistent control plane that self-populates LiveSharedRuntimeRegistry."""
from __future__ import annotations

import socket
import ssl
import threading
from typing import Any, Mapping

from protocol.node_identity import Ed25519ChallengeVerifier
from protocol.node_session import SessionSnapshot
from protocol.session_wire import BenchmarkAcceptanceDecision
from services.orchestrator.live_provider_registration import (
    LiveProviderRegistration,
    accept_live_authenticated_provider,
)
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry
from services.orchestrator.persistent_control_channel import PersistentNodeControlClient


class LiveBenchmarkAcceptancePolicy:
    """Accept only scheduler-relevant benchmark families bound by NodeSessionWireHandler."""

    ALLOWED = frozenset({"llama_cpp_prefill", "llama_cpp_decode", "tcp_network_path"})

    def evaluate(self, *, report: Mapping[str, Any], session: SessionSnapshot, now: Any) -> BenchmarkAcceptanceDecision:
        name = report.get("benchmark_name")
        if name not in self.ALLOWED:
            return BenchmarkAcceptanceDecision(False, reason="benchmark family is not accepted for live shared scheduling")
        return BenchmarkAcceptanceDecision(True, ready=False)


class IntegratedLiveControlPlane:
    """TLS listener + Ed25519 session auth + automatic live scheduling registration."""

    def __init__(
        self,
        *,
        registry: LiveSharedRuntimeRegistry,
        verifier: Ed25519ChallengeVerifier,
        host: str,
        port: int,
        cert_file: str,
        key_file: str,
        control_plane_id: str = "computemesh-control-plane",
        heartbeat_interval_seconds: float = 15.0,
        stale_after_seconds: float = 45.0,
    ) -> None:
        if heartbeat_interval_seconds <= 0 or stale_after_seconds <= heartbeat_interval_seconds:
            raise ValueError("heartbeat/stale intervals are invalid")
        self.registry = registry
        self.verifier = verifier
        self.host = host
        self.port = port
        self.control_plane_id = control_plane_id
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.stale_after_seconds = stale_after_seconds
        self.control_client = PersistentNodeControlClient()
        self.registration = LiveProviderRegistration(registry)
        self.benchmark_policy = LiveBenchmarkAcceptancePolicy()
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        self._listener: socket.socket | None = None
        self._stop = threading.Event()
        self.registry.set_control_client(self.control_client)

    @property
    def bound_port(self) -> int:
        return self.port if self._listener is None else int(self._listener.getsockname()[1])

    def start(self) -> None:
        if self._listener is not None:
            raise RuntimeError("live control plane already started")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(64)
        listener.settimeout(1.0)
        self._listener = listener
        threading.Thread(target=self._accept_loop, name="cm-live-control-accept", daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, name="cm-live-control-heartbeat", daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        listener, self._listener = self._listener, None
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
            threading.Thread(target=self._authenticate, args=(raw,), daemon=True).start()

    def _authenticate(self, raw: socket.socket) -> None:
        wrapped: ssl.SSLSocket | None = None
        transferred = False
        try:
            wrapped = self._context.wrap_socket(raw, server_side=True)
            accept_live_authenticated_provider(
                sock=wrapped,
                verifier=self.verifier,
                benchmark_policy=self.benchmark_policy,
                control_client=self.control_client,
                registration=self.registration,
                control_plane_id=self.control_plane_id,
                control_plane_capabilities=("execution_attestation_v1", "live_runtime_registration_v1"),
            )
            transferred = True
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
            self.control_client.heartbeat_once(stale_after_seconds=self.stale_after_seconds)
