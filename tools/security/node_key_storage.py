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
import os
from pathlib import Path
import platform
import secrets
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DPAPI_ENVELOPE_PREFIX = "cm-dpapi-v1:"


class KeyStorageError(RuntimeError):
    """Base error for node key storage operations."""


class KeyProtectionError(KeyStorageError):
    """Raised when OS protection (e.g. DPAPI) fails."""


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

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform.system().lower() != "windows":
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass

    pem_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    if protect_os and platform.system().lower() == "windows" and _HAS_DPAPI:
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
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def load_node_private_key(path: Path) -> Ed25519PrivateKey:
    """Loads and decrypts (if necessary) an Ed25519 private key from disk."""
    if path.is_symlink() or not path.is_file():
        raise KeyStorageError(f"key file is missing or invalid symlink: {path}")

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
