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
import logging
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

logger = logging.getLogger("computemesh.mesh_transport")


class MeshTransportError(RuntimeError):
    """Base exception for mesh transport and handshake errors."""


@dataclass(frozen=True)
class MeshCACredentials:
    ca_cert_pem: bytes
    ca_key_pem: bytes
    ca_cert_path: Path
    ca_key_path: Path


@dataclass(frozen=True)
class NodeCredentials:
    node_id: str
    cert_pem: bytes
    key_pem: bytes
    cert_path: Path
    key_path: Path
    ca_cert_path: Path | None = None


def generate_mesh_ca(temp_dir: Path) -> MeshCACredentials:
    """Generates a self-signed root Certificate Authority for the ComputeMesh cluster."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "ComputeMesh Root CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ComputeMesh Decentralized Network"),
    ])

    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=5))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_cert_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
    ca_key_pem = ca_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    ca_cert_path = temp_dir / "computemesh_mesh_ca_cert.pem"
    ca_key_path = temp_dir / "computemesh_mesh_ca_key.pem"
    ca_cert_path.write_bytes(ca_cert_pem)
    ca_key_path.write_bytes(ca_key_pem)

    return MeshCACredentials(
        ca_cert_pem=ca_cert_pem,
        ca_key_pem=ca_key_pem,
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
    )


def generate_node_tls_credentials(
    node_id: str,
    temp_dir: Path,
    ca_creds: MeshCACredentials | None = None,
) -> NodeCredentials:
    """Generates an ephemeral RSA/TLS certificate for mutual authentication.
    If no ca_creds is passed, creates or uses a shared local CA in temp_dir.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    if ca_creds is None:
        ca_creds = generate_mesh_ca(temp_dir)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"node-{node_id}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ComputeMesh Decentralized Network"),
    ])

    ca_cert = x509.load_pem_x509_certificate(ca_creds.ca_cert_pem)
    ca_key = serialization.load_pem_private_key(ca_creds.ca_key_pem, password=None)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=5))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName(f"node-{node_id}"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.ExtendedKeyUsageOID.SERVER_AUTH,
                x509.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
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
        ca_cert_path=ca_creds.ca_cert_path,
    )


def extract_node_id_from_cert(peer_cert: dict[str, Any] | None) -> str | None:
    """Extracts node identifier from peer certificate Subject Common Name."""
    if not peer_cert:
        return None
    for rdn in peer_cert.get("subject", ()):
        for k, v in rdn:
            if k == "commonName":
                if str(v).startswith("node-"):
                    return str(v).removeprefix("node-")
                return str(v)
    return None


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
        ctx.load_cert_chain(certfile=str(self.server_creds.cert_path), keyfile=str(self.server_creds.key_path))
        
        # Enforce strict Mutual TLS (mTLS) with CA verification
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = False
        if self.server_creds.ca_cert_path and self.server_creds.ca_cert_path.exists():
            ctx.load_verify_locations(cafile=str(self.server_creds.ca_cert_path))
        else:
            ctx.load_verify_locations(cafile=str(self.server_creds.cert_path))

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
            # Cryptographic identity validation of connecting peer
            peer_cert = client_ssl.getpeercert()
            client_node_id = extract_node_id_from_cert(peer_cert)
            if not client_node_id:
                logger.warning("Rejected mTLS connection: Missing or invalid peer certificate.")
                client_ssl.close()
                return

            if self.allowed_client_nodes is not None and client_node_id not in self.allowed_client_nodes:
                logger.warning(f"Rejected mTLS connection: Node '{client_node_id}' not in allowed_client_nodes.")
                client_ssl.close()
                return

            target_sock = socket.create_connection((self.target_host, self.target_port), timeout=5)
            # Bidirectional pipe
            t1 = threading.Thread(target=self._pipe, args=(client_ssl, target_sock, "c2t"), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(target_sock, client_ssl, "t2c"), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception as e:
            logger.debug(f"mTLS client session error: {e}")
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
                if not isinstance(dst, ssl.SSLSocket):
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
        expected_server_node_id: str | None = None,
    ) -> None:
        self.local_listen_host = local_listen_host
        self.local_listen_port = local_listen_port
        self.remote_tunnel_host = remote_tunnel_host
        self.remote_tunnel_port = remote_tunnel_port
        self.client_creds = client_creds
        self.expected_server_node_id = expected_server_node_id
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
            ctx.load_cert_chain(certfile=str(self.client_creds.cert_path), keyfile=str(self.client_creds.key_path))
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.check_hostname = False
            if self.client_creds.ca_cert_path and self.client_creds.ca_cert_path.exists():
                ctx.load_verify_locations(cafile=str(self.client_creds.ca_cert_path))
            else:
                ctx.load_verify_locations(cafile=str(self.client_creds.cert_path))

            raw_sock = socket.create_connection((self.remote_tunnel_host, self.remote_tunnel_port), timeout=5)
            ssl_sock = ctx.wrap_socket(raw_sock, server_hostname="localhost")

            # Validate server peer certificate and expected node identity
            peer_cert = ssl_sock.getpeercert()
            server_node_id = extract_node_id_from_cert(peer_cert)
            if self.expected_server_node_id is not None and server_node_id != self.expected_server_node_id:
                logger.warning(f"mTLS server identity mismatch: expected '{self.expected_server_node_id}', got '{server_node_id}'")
                ssl_sock.close()
                return

            t1 = threading.Thread(target=self._pipe, args=(app_sock, ssl_sock, "a2s"), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(ssl_sock, app_sock, "s2a"), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception as e:
            logger.debug(f"mTLS app tunnel error: {e}")
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
                if not isinstance(dst, ssl.SSLSocket):
                    dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass
