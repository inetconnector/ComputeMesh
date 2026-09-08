"""ComputeMesh Local LAN P2P Discovery Responder.

Listens on UDP port 13379 for local network discovery broadcasts
from Android smartphones and other LAN clients.
Enables 100% zero-server local P2P pairing and compute offloading.
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Any, Optional

logger = logging.getLogger("LAN-Discovery-Responder")
DISCOVERY_PORT = 13379
DISCOVERY_PROBE_MESSAGE = "COMPUTEMESH_DISCOVERY_PING"


class LanDiscoveryResponder:
    """UDP listener responding to local discovery probes."""

    def __init__(
        self,
        node_id: str = "computemesh-node",
        port: int = 8000,
        gpu_summary: str = "Local GPU Compute",
        bind_host: str = "0.0.0.0",
    ) -> None:
        self.node_id = node_id
        self.port = port
        self.gpu_summary = gpu_summary
        self.bind_host = bind_host
        self._running = False
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Starts the UDP listener thread."""
        if self._running:
            return True

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                # Allow broadcast reception
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except Exception:
                pass
            self._sock.bind((self.bind_host, DISCOVERY_PORT))
            self._sock.settimeout(1.0)
            self._running = True
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            logger.info("LAN Discovery Responder active on UDP port %d (node: %s)", DISCOVERY_PORT, self.node_id)
            return True
        except Exception as exc:
            logger.warning("Could not bind UDP discovery port %d: %s", DISCOVERY_PORT, exc)
            self.stop()
            return False

    def _listen_loop(self) -> None:
        while self._running and self._sock:
            try:
                data, addr = self._sock.recvfrom(2048)
                msg = data.decode("utf-8", errors="ignore").strip()
                if msg == DISCOVERY_PROBE_MESSAGE or msg.startswith("COMPUTEMESH_DISCOVERY_PING"):
                    # Format: COMPUTEMESH_PONG:<nodeId>;<port>;<gpuSummary>
                    response = f"COMPUTEMESH_PONG:{self.node_id};{self.port};{self.gpu_summary}".encode("utf-8")
                    self._sock.sendto(response, addr)
                    logger.debug("Sent discovery pong to %s for node %s", addr, self.node_id)
            except socket.timeout:
                continue
            except Exception as exc:
                if self._running:
                    logger.debug("Discovery socket read issue: %s", exc)

    def update_status(self, node_id: str, gpu_summary: str, port: int = 8000) -> None:
        """Updates the broadcasted node status."""
        self.node_id = node_id
        self.gpu_summary = gpu_summary
        self.port = port

    def stop(self) -> None:
        """Stops the UDP listener."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


_GLOBAL_RESPONDER: Optional[LanDiscoveryResponder] = None
_LOCK = threading.Lock()


def start_lan_discovery_responder(
    node_id: str = "computemesh-node",
    port: int = 8000,
    gpu_summary: str = "Local Compute Node",
) -> Optional[LanDiscoveryResponder]:
    """Starts or returns the global singleton LAN discovery responder."""
    global _GLOBAL_RESPONDER
    with _LOCK:
        if _GLOBAL_RESPONDER is None:
            _GLOBAL_RESPONDER = LanDiscoveryResponder(node_id=node_id, port=port, gpu_summary=gpu_summary)
            _GLOBAL_RESPONDER.start()
        else:
            _GLOBAL_RESPONDER.update_status(node_id, gpu_summary, port)
        return _GLOBAL_RESPONDER
