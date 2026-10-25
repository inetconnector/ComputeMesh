#!/usr/bin/env python3
"""ComputeMesh Cryptographic Release Signer & Keypair Manager (Ed25519).

Generates and persists the Master Ed25519 release signing keypair to \\\\diskstation\\Dani\\ComputeMesh,
calculates SHA-256 checksums across all release binaries, and produces digitally signed
update manifests (version.json) that clients verify before applying any update.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from tools.security.signing_keys import TRUSTED_RELEASE_PUBLIC_KEYS_HEX

DISKSTATION_PATH = Path(r"\\diskstation\Dani\ComputeMesh")
# Must never live inside a git working tree: a home-directory secrets folder
# is not a project directory and cannot be swept up by a repo/project backup
# (e.g. zipping the checkout) the way REPO_ROOT/config/security was.
LOCAL_BACKUP_PATH = Path.home() / ".computemesh" / "secrets"
SIGNING_KEYS_FILE = Path(__file__).resolve().parent / "signing_keys.py"


def get_or_create_keypair(allow_generate: bool = False) -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Retrieve existing master keypair from DiskStation or local backup.

    To preserve the trust chain across existing node installations, this function
    fails closed if the official release signing key is not found, refusing to
    automatically generate arbitrary new keys without explicit authorization.
    """
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

    if not allow_generate:
        raise FileNotFoundError(
            f"Master release signing private key not found at DiskStation ({DISKSTATION_PATH}) "
            f"or local backup ({LOCAL_BACKUP_PATH}). Refusing to automatically generate arbitrary new keys."
        )

    # Generate new Ed25519 Master Keypair only with explicit authorization
    print("Generating new Master Ed25519 Release Signing Keypair (explicit authorization)...")
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
        except OSError as e:
            print(f"Warning: Could not write to DiskStation: {e}")

    # Save to local backup (outside the repo tree; see LOCAL_BACKUP_PATH).
    LOCAL_BACKUP_PATH.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(LOCAL_BACKUP_PATH, 0o700)
    except OSError:
        pass
    local_private_key_file.write_bytes(priv_raw)
    try:
        os.chmod(local_private_key_file, 0o600)
    except OSError:
        pass
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
    base_url: str = f"{CONFIG.endpoints.base_url}/downloads",
    staging_dir: Path | None = None,
    allow_partial: bool = False,
    allow_generate: bool = False,
) -> dict[str, Any]:
    """Generate and cryptographically sign update manifest from verified files on disk.

    Operates strictly fail-closed: Every published artifact must physically exist as
    a readable binary, with SHA-256 and byte sizes computed directly from real bytes.
    Hardcoded hash fallbacks and unverified historical carryover are strictly prohibited.
    """
    priv_key, pub_key = get_or_create_keypair(allow_generate=allow_generate)
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

    missing_targets: list[str] = []

    for platform_id, filename in targets.items():
        # Check downloads_dir first, then staging_dir if provided
        file_path = downloads_dir / filename
        if not file_path.exists() and staging_dir is not None:
            staged = staging_dir / filename
            if staged.exists():
                file_path = staged

        if file_path.exists() and file_path.stat().st_size > 0:
            sha = compute_sha256(file_path)
            size = file_path.stat().st_size
            artifacts[platform_id] = {
                "filename": filename,
                "url": f"{base_url}/{filename}",
                "sha256": sha,
                "size_bytes": size,
            }
            print(f"  [VERIFIED ARTIFACT] {platform_id}: {filename} ({size:,} bytes | SHA-256: {sha})")
        else:
            missing_targets.append(f"{platform_id} ({filename})")

    if missing_targets and not allow_partial:
        raise FileNotFoundError(
            f"Release signing failed: missing mandatory physical release binaries on disk: "
            f"{', '.join(missing_targets)}. "
            f"All release artifacts must be physically present and verified before signing."
        )

    manifest_data = {
        "version": version,
        "release_date": datetime.now(UTC).isoformat(),
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
    if pub_hex.lower() not in {key.lower() for key in TRUSTED_RELEASE_PUBLIC_KEYS_HEX}:
        print("Signature verification failed: manifest key is not trusted")
        return False

    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        canonical_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        pub_key.verify(bytes.fromhex(sig_hex), canonical_bytes)
        return True
    except (InvalidSignature, ValueError) as e:
        print(f"Signature verification failed: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Cryptographic Release Signer")
    parser.add_argument("--version", default=CONFIG.appliance_version, help="Release version string")
    parser.add_argument("--downloads-dir", default="portal/downloads", help="Directory containing release binaries")
    parser.add_argument("--staging-dir", default=None, help="Optional staging directory containing built binaries")
    parser.add_argument("--output", default="portal/updates/version.json", help="Output path for signed manifest")
    parser.add_argument("--allow-partial", action="store_true", help="Allow signing a subset of platforms (development/testing)")
    parser.add_argument("--generate-key", action="store_true", help="Allow generating a new master Ed25519 key if missing")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    d_dir = repo_root / args.downloads_dir
    st_dir = repo_root / args.staging_dir if args.staging_dir else None
    out_file = repo_root / args.output

    sign_manifest(
        version=args.version,
        downloads_dir=d_dir,
        output_manifest=out_file,
        staging_dir=st_dir,
        allow_partial=args.allow_partial,
        allow_generate=args.generate_key,
    )
    is_valid = verify_manifest(out_file)
    print(f"Verification Check: {'[VALID]' if is_valid else '[INVALID]'}")
    return 0 if is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
