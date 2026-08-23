#!/usr/bin/env python3
"""ComputeMesh Cryptographic Release Signer & Keypair Manager (Ed25519).

Generates and persists the Master Ed25519 release signing keypair to \\\\diskstation\\Dani\\ComputeMesh,
calculates SHA-256 checksums across all release binaries, and produces digitally signed
update manifests (version.json) that clients verify before applying any update.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

DISKSTATION_PATH = Path(r"\\diskstation\Dani\ComputeMesh")
LOCAL_BACKUP_PATH = Path(__file__).resolve().parents[2] / "config" / "security"
SIGNING_KEYS_FILE = Path(__file__).resolve().parent / "signing_keys.py"


def get_or_create_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Retrieve existing master keypair or generate a new one at \\\\diskstation\\Dani\\ComputeMesh."""
    ds_private_key_file = DISKSTATION_PATH / "computemesh_release_signing_private.key"
    ds_public_key_file = DISKSTATION_PATH / "computemesh_release_signing_public.key"
    local_private_key_file = LOCAL_BACKUP_PATH / "computemesh_release_signing_private.key"

    # Check if key already exists on DiskStation
    if ds_private_key_file.exists():
        priv_bytes = ds_private_key_file.read_bytes()
        priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
        pub_key = priv_key.public_key()
        return priv_key, pub_key

    # Check local backup
    if local_private_key_file.exists():
        priv_bytes = local_private_key_file.read_bytes()
        priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
        pub_key = priv_key.public_key()
        return priv_key, pub_key

    # Generate new Ed25519 Master Keypair
    print("Generating new Master Ed25519 Release Signing Keypair...")
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    priv_raw = priv_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # Save to DiskStation if accessible
    if DISKSTATION_PATH.exists():
        try:
            ds_private_key_file.write_bytes(priv_raw)
            ds_public_key_file.write_text(pub_raw.hex() + "\n", encoding="utf-8")
            print(f"Saved master private key to {ds_private_key_file}")
        except Exception as e:
            print(f"Warning: Could not write to DiskStation: {e}")

    # Save to local backup
    LOCAL_BACKUP_PATH.mkdir(parents=True, exist_ok=True)
    local_private_key_file.write_bytes(priv_raw)
    (LOCAL_BACKUP_PATH / "computemesh_release_signing_public.key").write_text(pub_raw.hex() + "\n", encoding="utf-8")

    # Update signing_keys.py with new public key hex
    update_embedded_public_key(pub_raw.hex())

    return priv_key, pub_key


def update_embedded_public_key(pub_hex: str) -> None:
    """Update OFFICIAL_RELEASE_PUBLIC_KEY_HEX in signing_keys.py."""
    if SIGNING_KEYS_FILE.exists():
        content = f'''"""ComputeMesh Public Key Store for Release Signature Verification.

This file embeds the official inetconnector Ed25519 public key used by all
client nodes (Windows, Linux, NodeOS) to verify the authenticity of updates.
"""
from __future__ import annotations

# Official inetconnector ComputeMesh Ed25519 Public Key (Hex / Raw)
# Matches the Master Private Key stored securely at \\\\diskstation\\Dani\\ComputeMesh
OFFICIAL_RELEASE_PUBLIC_KEY_HEX: str = "{pub_hex}"


def get_official_public_key_bytes() -> bytes:
    """Return raw 32-byte public key."""
    return bytes.fromhex(OFFICIAL_RELEASE_PUBLIC_KEY_HEX)
'''
        SIGNING_KEYS_FILE.write_text(content, encoding="utf-8")
        print(f"Updated embedded public key in {SIGNING_KEYS_FILE}")


def compute_sha256(file_path: Path) -> str:
    """Calculate SHA-256 hexadecimal hash for a binary file."""
    if not file_path.exists():
        return ""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sign_manifest(
    version: str,
    downloads_dir: Path,
    output_manifest: Path,
    base_url: str = "https://computemesh.inetconnector.com/downloads",
) -> dict[str, Any]:
    """Generate and cryptographically sign update manifest."""
    priv_key, pub_key = get_or_create_keypair()
    pub_raw = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    artifacts: dict[str, dict[str, Any]] = {}

    targets = {
        "windows-x64": "ComputeMesh-Setup-x64.exe",
        "linux-x64": "computemesh-linux-x86_64.tar.gz",
        "nodeos-iso": "computemesh-nodeos-x86_64.iso",
        "nodeos-img": "computemesh-nodeos-x86_64.img.xz",
        "installer-script": "install.sh",
    }

    for platform_id, filename in targets.items():
        file_path = downloads_dir / filename
        if file_path.exists():
            sha = compute_sha256(file_path)
            size = file_path.stat().st_size
            artifacts[platform_id] = {
                "filename": filename,
                "url": f"{base_url}/{filename}",
                "sha256": sha,
                "size_bytes": size,
            }

    manifest_data = {
        "version": version,
        "release_date": datetime.now(timezone.utc).isoformat(),
        "min_compatible_version": "1.0.0",
        "public_key": pub_raw.hex(),
        "platforms": artifacts,
    }

    # Canonical JSON string for signature
    canonical_bytes = json.dumps(manifest_data, sort_keys=True).encode("utf-8")
    signature = priv_key.sign(canonical_bytes)

    full_manifest = {
        **manifest_data,
        "signature": signature.hex(),
    }

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(full_manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Signed release manifest written to {output_manifest}")
    return full_manifest


def verify_manifest(manifest_path: Path) -> bool:
    """Verify digital Ed25519 signature of an update manifest."""
    if not manifest_path.exists():
        return False
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    sig_hex = data.pop("signature", None)
    if not sig_hex:
        return False

    pub_hex = data.get("public_key")
    if not pub_hex:
        return False

    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        canonical_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        pub_key.verify(bytes.fromhex(sig_hex), canonical_bytes)
        return True
    except Exception as e:
        print(f"Signature verification failed: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Cryptographic Release Signer")
    parser.add_argument("--version", default="1.2.6", help="Release version string")
    parser.add_argument("--downloads-dir", default="portal/downloads", help="Directory containing release binaries")
    parser.add_argument("--output", default="portal/updates/version.json", help="Output path for signed manifest")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    d_dir = repo_root / args.downloads_dir
    out_file = repo_root / args.output

    sign_manifest(args.version, d_dir, out_file)
    is_valid = verify_manifest(out_file)
    print(f"Verification Check: {'[VALID]' if is_valid else '[INVALID]'}")
    return 0 if is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
