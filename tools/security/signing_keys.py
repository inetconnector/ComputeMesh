"""ComputeMesh Public Key Store for Release Signature Verification.

This file embeds the official inetconnector Ed25519 public key used by all
client nodes (Windows, Linux, NodeOS) to verify the authenticity of updates.
"""
from __future__ import annotations

# Official inetconnector ComputeMesh Ed25519 Public Key (Hex / Raw)
# Matches the Master Private Key stored securely at \\diskstation\Dani\ComputeMesh
OFFICIAL_RELEASE_PUBLIC_KEY_HEX: str = "0f559b72426bc24e12bd67790af054b2dba713bf0deb1bcc2faf0dfa1200f2bc"


def get_official_public_key_bytes() -> bytes:
    """Return raw 32-byte public key."""
    return bytes.fromhex(OFFICIAL_RELEASE_PUBLIC_KEY_HEX)
