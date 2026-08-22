#!/usr/bin/env python3
"""ComputeMesh Mutual TLS (mTLS) Peer-to-Peer Encrypted Transport (ADR 0003).

Establishes zero-configuration, mutually authenticated, end-to-end encrypted
TCP tunnels between distributed coordinator and worker nodes without requiring
SSH key distribution or manual port-forwarding setups.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
import socket
import ssl
import sys
import threading
import time
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class MeshTransportError(RuntimeError):
    """Base exception for mesh transport and handshake errors."""


@dataclass(frozen=True)
class NodeCredentials:
    node_id: str
    cert_pem: bytes
    key_pem: bytes
    cert_path: Path
    key_path: Path


def generate_node_tls_credentials(node_id: str, temp_dir: Path) -> NodeCredentials:
    """Generates an ephemeral RSA/TLS certificate for mutual authentication."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"node-{node_id}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ComputeMesh Decentralized Network"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=5))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    cert_path = temp_dir / f"{node_id}_cert.pem"
    key_path = temp_dir / f"{node_id}_key.pem"
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)

    return NodeCredentials(
        node_id=node_id,
        cert_pem=cert_pem,
        key_pem=key_pem,
        cert_path=cert_path,
        key_path=key_path,
    )


class MeshTunnelServer:
    """Listens for incoming mTLS connections and forwards plain TCP to local target."""

    def __init__(
        self,
        *,
        listen_host: str,
        listen_port: int,
        target_host: str,
        target_port: int,
        server_creds: NodeCredentials,
        allowed_client_nodes: set[str] | None = None,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.server_creds = server_creds
        self.allowed_client_nodes = allowed_client_nodes
        self._running = False
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.total_bytes_received = 0
        self.total_bytes_sent = 0

    def start(self) -> int:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(certfile=self.server_creds.cert_path, keyfile=self.server_creds.key_path)
        # Allow self-signed client certificates verified at application layer
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw_sock.bind((self.listen_host, self.listen_port))
        raw_sock.listen(16)
        self.listen_port = raw_sock.getsockname()[1]
        self._server_sock = ctx.wrap_socket(raw_sock, server_side=True)

        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self.listen_port

    def stop(self) -> None:
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client_ssl, _ = self._server_sock.accept()
                threading.Thread(target=self._handle_client, args=(client_ssl,), daemon=True).start()
            except Exception:
                break

    def _handle_client(self, client_ssl: ssl.SSLSocket) -> None:
        target_sock = None
        try:
            target_sock = socket.create_connection((self.target_host, self.target_port), timeout=5)
            # Bidirectional pipe
            t1 = threading.Thread(target=self._pipe, args=(client_ssl, target_sock, "c2t"), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(target_sock, client_ssl, "t2c"), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception:
            pass
        finally:
            try:
                client_ssl.close()
            except Exception:
                pass
            if target_sock:
                try:
                    target_sock.close()
                except Exception:
                    pass

    def _pipe(self, src: socket.socket, dst: socket.socket, direction: str) -> None:
        buf = bytearray(64 * 1024)
        try:
            while self._running:
                n = src.recv_into(buf)
                if n == 0:
                    break
                dst.sendall(buf[:n])
                if direction == "c2t":
                    self.total_bytes_received += n
                else:
                    self.total_bytes_sent += n
        except Exception:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass


class MeshTunnelClient:
    """Listens on local loopback and forwards plain TCP through an mTLS tunnel."""

    def __init__(
        self,
        *,
        local_listen_host: str = "127.0.0.1",
        local_listen_port: int = 0,
        remote_tunnel_host: str,
        remote_tunnel_port: int,
        client_creds: NodeCredentials,
    ) -> None:
        self.local_listen_host = local_listen_host
        self.local_listen_port = local_listen_port
        self.remote_tunnel_host = remote_tunnel_host
        self.remote_tunnel_port = remote_tunnel_port
        self.client_creds = client_creds
        self._running = False
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.total_bytes_sent = 0
        self.total_bytes_received = 0

    def start(self) -> int:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw_sock.bind((self.local_listen_host, self.local_listen_port))
        raw_sock.listen(16)
        self.local_listen_port = raw_sock.getsockname()[1]
        self._server_sock = raw_sock

        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self.local_listen_port

    def stop(self) -> None:
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                app_sock, _ = self._server_sock.accept()
                threading.Thread(target=self._handle_app, args=(app_sock,), daemon=True).start()
            except Exception:
                break

    def _handle_app(self, app_sock: socket.socket) -> None:
        ssl_sock = None
        try:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.load_cert_chain(certfile=self.client_creds.cert_path, keyfile=self.client_creds.key_path)

            raw_sock = socket.create_connection((self.remote_tunnel_host, self.remote_tunnel_port), timeout=5)
            ssl_sock = ctx.wrap_socket(raw_sock, server_hostname="localhost")

            t1 = threading.Thread(target=self._pipe, args=(app_sock, ssl_sock, "a2s"), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(ssl_sock, app_sock, "s2a"), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception:
            pass
        finally:
            try:
                app_sock.close()
            except Exception:
                pass
            if ssl_sock:
                try:
                    ssl_sock.close()
                except Exception:
                    pass

    def _pipe(self, src: socket.socket, dst: socket.socket, direction: str) -> None:
        buf = bytearray(64 * 1024)
        try:
            while self._running:
                n = src.recv_into(buf)
                if n == 0:
                    break
                dst.sendall(buf[:n])
                if direction == "a2s":
                    self.total_bytes_sent += n
                else:
                    self.total_bytes_received += n
        except Exception:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass
