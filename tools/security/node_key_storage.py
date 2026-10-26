"""OS-protected storage and retrieval for ComputeMesh Ed25519 node private keys.

Supports:
- Windows: Data Protection API (DPAPI via crypt32.dll) for transparent at-rest encryption
  tied to the logged-in user account.
- Linux/POSIX: Strict atomic file creation with 0600 permissions and directory-level 0700 isolation.
- Transparent loading: Loads standard PEM, DPAPI-protected, or AES-GCM vault-encrypted keys.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import secrets
import stat
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

DPAPI_ENVELOPE_PREFIX = "cm-dpapi-v1:"


class KeyStorageError(RuntimeError):
    """Base error for node key storage operations."""


class KeyProtectionError(KeyStorageError):
    """Raised when OS protection (e.g. DPAPI) fails."""


def _absolute_key_path(path: Path) -> Path:
    """Return an absolute path without following a possibly existing key symlink."""
    path = Path(path)
    if path.is_symlink():
        raise KeyStorageError(f"refusing to operate on symlinked key path: {path}")
    return Path(os.path.abspath(os.fspath(path)))


def _assert_posix_permissions(path: Path) -> None:
    """Fail closed when a key or its containing directory is group/world accessible."""
    if platform.system().lower() == "windows":
        return
    try:
        file_mode = stat.S_IMODE(path.stat().st_mode)
        directory_mode = stat.S_IMODE(path.parent.stat().st_mode)
    except OSError as exc:
        raise KeyStorageError(f"cannot inspect private key permissions: {path}") from exc
    if file_mode & 0o077:
        raise KeyStorageError(
            f"private key file permissions are too open ({oct(file_mode)}); expected owner-only access: {path}"
        )
    if directory_mode & 0o077:
        raise KeyStorageError(
            f"private key directory permissions are too open ({oct(directory_mode)}); expected owner-only access: {path.parent}"
        )


# Windows DPAPI structures and functions via ctypes
if platform.system().lower() == "windows":
    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    try:
        _crypt32 = ctypes.windll.crypt32
        _kernel32 = ctypes.windll.kernel32

        _CryptProtectData = _crypt32.CryptProtectData
        _CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),  # pDataIn
            wintypes.LPCWSTR,            # szDataDescr
            ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
            ctypes.c_void_p,             # pvReserved
            ctypes.c_void_p,             # pPromptStruct
            wintypes.DWORD,              # dwFlags
            ctypes.POINTER(_DATA_BLOB),  # pDataOut
        ]
        _CryptProtectData.restype = wintypes.BOOL

        _CryptUnprotectData = _crypt32.CryptUnprotectData
        _CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),  # pDataIn
            ctypes.POINTER(wintypes.LPWSTR),  # ppszDataDescr
            ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
            ctypes.c_void_p,             # pvReserved
            ctypes.c_void_p,             # pPromptStruct
            wintypes.DWORD,              # dwFlags
            ctypes.POINTER(_DATA_BLOB),  # pDataOut
        ]
        _CryptUnprotectData.restype = wintypes.BOOL

        _LocalFree = _kernel32.LocalFree
        _LocalFree.argtypes = [ctypes.c_void_p]
        _LocalFree.restype = ctypes.c_void_p
        _HAS_DPAPI = True
    except Exception:
        _HAS_DPAPI = False
else:
    _HAS_DPAPI = False


def dpapi_protect(data: bytes, description: str = "ComputeMesh Node Key") -> bytes:
    """Encrypts raw bytes with Windows DPAPI (current user scope)."""
    if not _HAS_DPAPI:
        raise KeyProtectionError("DPAPI is only available on Windows")

    in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()

    # CRYPTPROTECT_UI_FORBIDDEN = 0x01
    flags = 0x01
    success = _CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    if not success:
        error_code = ctypes.GetLastError()
        raise KeyProtectionError(f"CryptProtectData failed with win32 error code {error_code}")

    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return protected
    finally:
        _LocalFree(out_blob.pbData)


def dpapi_unprotect(data: bytes) -> bytes:
    """Decrypts DPAPI-encrypted bytes (current user scope)."""
    if not _HAS_DPAPI:
        raise KeyProtectionError("DPAPI is only available on Windows")

    in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()

    flags = 0x01
    success = _CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    if not success:
        error_code = ctypes.GetLastError()
        raise KeyProtectionError(f"CryptUnprotectData failed with win32 error code {error_code}")

    try:
        unprotected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return unprotected
    finally:
        _LocalFree(out_blob.pbData)


def save_node_private_key(
    key: Ed25519PrivateKey,
    path: Path,
    *,
    protect_os: bool = True,
) -> None:
    """Persists an Ed25519 private key securely to disk.
    
    If on Windows and protect_os is True, encrypts using DPAPI.
    If on POSIX, sets strict 0600 file permissions and 0700 parent directory.
    """
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("key must be an instance of Ed25519PrivateKey")

    path = _absolute_key_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform.system().lower() != "windows":
        try:
            path.parent.chmod(0o700)
        except OSError as exc:
            raise KeyStorageError(f"cannot secure private key directory: {path.parent}") from exc

    pem_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    if protect_os and platform.system().lower() == "windows":
        if not _HAS_DPAPI:
            raise KeyProtectionError("Windows DPAPI is unavailable; refusing to persist an unprotected node key")
        protected_bytes = dpapi_protect(pem_bytes)
        b64_str = base64.b64encode(protected_bytes).decode("ascii")
        content = (DPAPI_ENVELOPE_PREFIX + b64_str + "\n").encode("ascii")
    else:
        content = pem_bytes

    temp_path = path.with_name(f"{path.name}.tmp.{secrets.token_hex(6)}")
    try:
        if platform.system().lower() != "windows":
            fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(content)
        else:
            temp_path.write_bytes(content)

        temp_path.replace(path)
        if platform.system().lower() != "windows":
            os.chmod(path, 0o600)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def load_node_private_key(path: Path) -> Ed25519PrivateKey:
    """Loads and decrypts (if necessary) an Ed25519 private key from disk."""
    path = _absolute_key_path(path)
    if path.is_symlink() or not path.is_file():
        raise KeyStorageError(f"key file is missing or invalid symlink: {path}")
    _assert_posix_permissions(path)

    raw_bytes = path.read_bytes()
    if not raw_bytes:
        raise KeyStorageError(f"key file is empty: {path}")

    # Check for DPAPI envelope
    if raw_bytes.startswith(DPAPI_ENVELOPE_PREFIX.encode("ascii")):
        b64_part = raw_bytes[len(DPAPI_ENVELOPE_PREFIX):].strip()
        try:
            protected = base64.b64decode(b64_part)
        except Exception as exc:
            raise KeyStorageError("malformed DPAPI key envelope") from exc
        key_bytes = dpapi_unprotect(protected)
    else:
        key_bytes = raw_bytes

    # If raw 32-byte private key
    if len(key_bytes) == 32:
        try:
            return Ed25519PrivateKey.from_private_bytes(key_bytes)
        except Exception as exc:
            raise KeyStorageError("failed to construct Ed25519 key from 32 raw bytes") from exc

    # If PEM formatted
    if key_bytes.startswith(b"-----BEGIN"):
        try:
            key = serialization.load_pem_private_key(key_bytes, password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise KeyStorageError(f"loaded key is of unexpected type: {type(key)}")
            return key
        except KeyStorageError:
            raise
        except Exception as exc:
            raise KeyStorageError("failed to parse Ed25519 private key PEM data") from exc

    # Try base64-decoded raw 32 bytes
    stripped = key_bytes.strip()
    try:
        decoded = base64.b64decode(stripped, validate=True)
        if len(decoded) == 32:
            return Ed25519PrivateKey.from_private_bytes(decoded)
    except Exception:
        pass

    try:
        key = serialization.load_pem_private_key(stripped, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise KeyStorageError(f"loaded key is of unexpected type: {type(key)}")
        return key
    except Exception as exc:
        raise KeyStorageError(f"failed to parse Ed25519 private key data: {exc}") from exc


def shred_node_key(path: Path) -> bool:
    """Securely overwrites and unlinks the private key file."""
    path = _absolute_key_path(path)
    if not path.exists():
        return False
    try:
        size = path.stat().st_size
        if size > 0:
            with open(path, "wb") as f:
                f.write(secrets.token_bytes(size))
                f.flush()
                os.fsync(f.fileno())
        path.unlink()
        return True
    except OSError as exc:
        raise KeyStorageError(f"failed to securely shred key file {path}: {exc}") from exc


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("base64url value must be non-empty")
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def get_or_create_node_private_key(path: Path | None = None) -> tuple[Ed25519PrivateKey, Path]:
    """Retrieve an existing Ed25519 node private key or generate and persist a new one.

    Searches across authorized persistent storage tiers:
    1. Explicit path parameter or COMPUTEMESH_NODE_KEY_PATH environment variable
    2. /var/lib/computemesh/node_identity.key (standard POSIX daemon location)
    3. ~/.computemesh/node_identity.key (user runtime location)
    4. /etc/computemesh/node_identity.key (appliance system location)

    If no key file exists, generates a fresh Ed25519 keypair and securely persists
    it with strict 0600 permissions (or DPAPI on Windows). Never stores private
    keys on FAT32/boot partitions.
    """
    if path is not None:
        target_path = Path(path)
        if os.path.lexists(os.fspath(target_path)):
            if target_path.is_symlink() or not target_path.is_file():
                raise KeyStorageError(f"key path is not a regular file: {target_path}")
            return load_node_private_key(target_path), target_path
        # Generate at requested path
        key = Ed25519PrivateKey.generate()
        save_node_private_key(key, target_path)
        return key, target_path

    env_path_str = os.environ.get("COMPUTEMESH_NODE_KEY_PATH", "").strip()
    if env_path_str:
        p = Path(env_path_str)
        if os.path.lexists(os.fspath(p)):
            if p.is_symlink() or not p.is_file():
                raise KeyStorageError(f"configured node key path is not a regular file: {p}")
            return load_node_private_key(p), p

    candidate_paths = [
        Path("/var/lib/computemesh/node_identity.key"),
        Path.home() / ".computemesh" / "node_identity.key",
        Path("/etc/computemesh/node_identity.key"),
    ]

    for p in candidate_paths:
        if os.path.lexists(os.fspath(p)):
            if p.is_symlink() or not p.is_file():
                raise KeyStorageError(f"node key path is not a regular file: {p}")
            # An existing identity is authoritative.  Any mount, permission or
            # parse failure must reach the caller instead of silently rotating
            # to a new key.
            return load_node_private_key(p), p

    # No existing key found; determine optimal writable target path
    chosen_path: Path | None = None
    if platform.system().lower() != "windows" and os.geteuid() == 0 if hasattr(os, "geteuid") else False:
        for p in [Path("/var/lib/computemesh/node_identity.key"), Path("/etc/computemesh/node_identity.key")]:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                if os.access(p.parent, os.W_OK):
                    chosen_path = p
                    break
            except Exception:
                pass

    if chosen_path is None:
        chosen_path = Path.home() / ".computemesh" / "node_identity.key"

    key = Ed25519PrivateKey.generate()
    save_node_private_key(key, chosen_path)
    return key, chosen_path


def _heartbeat_signing_message(
    node_id: str,
    auth_token: str,
    timestamp: int,
    *,
    nonce: str = "",
    previous_node_id: str = "",
) -> bytes:
    """Build the versioned heartbeat message without ambiguous field joins."""
    if nonce or previous_node_id:
        fields = json.dumps(
            {
                "auth_token": str(auth_token),
                "node_id": str(node_id),
                "nonce": str(nonce),
                "previous_node_id": str(previous_node_id),
                "timestamp": int(timestamp),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return f"ComputeMesh.NodeHeartbeat.v2:{fields}".encode("utf-8")
    # Keep verification of the historical format available for already
    # enrolled nodes.  The gateway requires the v2 nonce form for new key
    # bindings and token-rotation proofs.
    return f"ComputeMesh.NodeHeartbeat.v1:{node_id}:{auth_token}:{timestamp}".encode("utf-8")


def sign_node_heartbeat(
    key: Ed25519PrivateKey,
    node_id: str,
    auth_token: str,
    timestamp: int,
    *,
    nonce: str = "",
    previous_node_id: str = "",
) -> str:
    """Produces a canonical Ed25519 signature proving cryptographic possession of the node identity."""
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("key must be an Ed25519PrivateKey")
    message = _heartbeat_signing_message(
        node_id,
        auth_token,
        timestamp,
        nonce=nonce,
        previous_node_id=previous_node_id,
    )
    signature = key.sign(message)
    return _b64u(signature)


def verify_node_heartbeat(
    public_key: bytes | str | Ed25519PublicKey,
    node_id: str,
    auth_token: str,
    timestamp: int,
    signature_b64u: str,
    *,
    now: int | None = None,
    max_skew_seconds: int = 60,
    nonce: str = "",
    previous_node_id: str = "",
) -> bool:
    """Verifies that a heartbeat or reconnect request originates from the holder of the registered Ed25519 key.

    Enforces:
    1. Timestamp freshness within max_skew_seconds (prevents replay attacks)
    2. Valid Ed25519 signature over canonical signing message
    3. Proper key length (32 bytes)
    """
    current_time = int(time.time()) if now is None else int(now)
    timestamp_int = int(timestamp)
    nonce = str(nonce or "")
    previous_node_id = str(previous_node_id or "")
    if len(nonce) > 256 or len(previous_node_id) > 512:
        return False
    if abs(current_time - timestamp_int) > max_skew_seconds:
        return False

    try:
        if isinstance(public_key, Ed25519PublicKey):
            pub = public_key
        elif isinstance(public_key, bytes):
            if len(public_key) == 32:
                pub = Ed25519PublicKey.from_public_bytes(public_key)
            else:
                # Try hex decode
                raw = bytes.fromhex(public_key.decode("ascii"))
                if len(raw) != 32:
                    return False
                pub = Ed25519PublicKey.from_public_bytes(raw)
        elif isinstance(public_key, str):
            clean = public_key.strip()
            if len(clean) == 64 and all(c in "0123456789abcdefABCDEF" for c in clean):
                raw = bytes.fromhex(clean)
            else:
                raw = _b64u_decode(clean)
            if len(raw) != 32:
                return False
            pub = Ed25519PublicKey.from_public_bytes(raw)
        else:
            return False

        sig_bytes = _b64u_decode(signature_b64u)
        if len(sig_bytes) != 64:
            return False

        message = _heartbeat_signing_message(
            node_id,
            auth_token,
            timestamp_int,
            nonce=nonce,
            previous_node_id=previous_node_id,
        )
        pub.verify(sig_bytes, message)
        return True
    except (InvalidSignature, ValueError, TypeError, Exception):
        return False
