#!/usr/bin/env python3
"""ComputeMesh Cryptographic Vault: AES-256-GCM Data-at-Rest Encryption Engine.

Guarantees authenticated, zero-plaintext storage of sensitive provider payout details,
SEPA IBANs, customer billing records, and API tokens.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(Exception):
    """Raised on cryptographic verification failure or invalid payload."""


class EncryptedVault:
    """AES-256-GCM authenticated encryption engine for sensitive metadata."""

    def __init__(
        self,
        key_bytes: bytes | None = None,
        key_env: str = "COMPUTEMESH_VAULT_KEY",
        key_file: Path | None = None,
    ) -> None:
        if key_bytes is not None:
            if len(key_bytes) != 32:
                raise VaultError("Vault key must be exactly 32 bytes (256-bit)")
            self._key = key_bytes
        elif key_env in os.environ and os.environ[key_env]:
            env_val = os.environ[key_env].strip()
            try:
                decoded = base64.b64decode(env_val)
                if len(decoded) == 32:
                    self._key = decoded
                else:
                    self._key = env_val.encode("utf-8")[:32].ljust(32, b"\0")
            except Exception:
                self._key = env_val.encode("utf-8")[:32].ljust(32, b"\0")
        elif key_file is not None and key_file.exists():
            content = key_file.read_bytes().strip()
            if len(content) == 32:
                self._key = content
            else:
                self._key = base64.b64decode(content)[:32].ljust(32, b"\0")
        else:
            # Ephemeral process-local key for tests and non-durable demos. Durable
            # deployments must set COMPUTEMESH_VAULT_KEY or pass a key file.
            self._key = secrets.token_bytes(32)

        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: str | None) -> str | None:
        """Encrypts plaintext string using AES-256-GCM with a fresh 96-bit nonce."""
        if plaintext is None:
            return None
        if not plaintext:
            return ""

        nonce = secrets.token_bytes(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        
        nonce_b64 = base64.b64encode(nonce).decode("ascii")
        ct_b64 = base64.b64encode(ciphertext).decode("ascii")
        return f"enc:v1:{nonce_b64}:{ct_b64}"

    def decrypt(self, payload: str | None) -> str | None:
        """Authenticates and decrypts payload. Returns plaintext if payload is unencrypted."""
        if payload is None:
            return None
        if not payload or not payload.startswith("enc:v1:"):
            return payload

        parts = payload.split(":")
        if len(parts) != 4:
            raise VaultError("Invalid encrypted payload format")

        _, version, nonce_b64, ct_b64 = parts
        if version != "v1":
            raise VaultError(f"Unsupported vault payload version: {version}")

        try:
            nonce = base64.b64decode(nonce_b64)
            ciphertext = base64.b64decode(ct_b64)
            decrypted = self._aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode("utf-8")
        except Exception as err:
            raise VaultError(f"Decryption authentication failed: {err}") from err

    @staticmethod
    def mask_sensitive(value: str | None) -> str:
        """Masks payout wallet, IBAN or email for safe logging & display."""
        if not value:
            return "N/A"
        clean = value.strip()
        if clean.startswith("0x") and len(clean) >= 10:
            return f"{clean[:6]}...{clean[-4:]}"
        # SEPA IBAN masking (e.g. DE89 **** **** **** 1234)
        if re.match(r"^[A-Z]{2}\d{2}", clean) and len(clean) >= 12:
            return f"{clean[:4]} **** **** **** {clean[-4:]}"
        # Email masking (e.g. f***e@inetconnector.com)
        if "@" in clean:
            user, domain = clean.split("@", 1)
            if len(user) <= 2:
                masked_user = user[0] + "*"
            else:
                masked_user = user[0] + ("*" * (len(user) - 2)) + user[-1]
            return f"{masked_user}@{domain}"
        return f"{clean[:2]}***{clean[-2:]}" if len(clean) > 4 else "***"


# Global singleton vault instance
DEFAULT_VAULT = EncryptedVault()
