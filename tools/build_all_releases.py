#!/usr/bin/env python3
"""ComputeMesh Master Release Builder.

Rebuilds all downloadable artifacts for Windows and Linux with latest code,
updates SHA-256 checksums, and signs version.json with the Master Ed25519 key.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VERSION = "1.2.31"
DOWNLOADS_DIR = REPO_ROOT / "portal" / "downloads"
UPDATES_DIR = REPO_ROOT / "portal" / "updates"


def build_linux_tarball() -> Path:
    """Pack all repository source directories into a clean Linux release archive."""
    print("\n[1/4] Packing Linux Release Package (computemesh-linux-x86_64.tar.gz)...")
    tar_path = DOWNLOADS_DIR / "computemesh-linux-x86_64.tar.gz"
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    include_dirs = [
        "services",
        "runtime",
        "tools",
        "deploy",
        "protocol",
        "config",
        "apps",
    ]
    include_files = [
        "config.py",
        "requirements.txt",
        "pyproject.toml",
        "README.md",
        "README.de.md",
        "ARCHITECTURE.md",
        "PROTOCOL.md",
        "SECURITY.md",
    ]

    def _filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        name = tarinfo.name
        # Skip temp and build caches
        if "__pycache__" in name or ".pytest_cache" in name or ".git" in name:
            return None
        if "portal/downloads" in name or "dist" in name or "build" in name:
            return None
        return tarinfo

    with tarfile.open(tar_path, "w:gz", compresslevel=9) as tar:
        for d in include_dirs:
            dp = REPO_ROOT / d
            if dp.exists():
                tar.add(dp, arcname=d, filter=_filter)
        for f in include_files:
            fp = REPO_ROOT / f
            if fp.exists():
                tar.add(fp, arcname=f)

    size = tar_path.stat().st_size
    sha = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    print(f"--> Linux Tarball built: {size:,} bytes | SHA256: {sha}")
    return tar_path


def build_windows_exe() -> Path:
    """Build standalone Windows installer executable via PyInstaller."""
    print("\n[2/4] Building Windows Standalone Executable (ComputeMesh-Setup-x64.exe)...")
    spec_file = REPO_ROOT / "ComputeMesh-Setup-x64.spec"
    dist_dir = REPO_ROOT / "dist"
    build_dir = REPO_ROOT / "build"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath", str(dist_dir),
        "--workpath", str(build_dir),
        str(spec_file),
    ]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)

    built_exe = dist_dir / "ComputeMesh-Setup-x64.exe"
    target_exe = DOWNLOADS_DIR / "ComputeMesh-Setup-x64.exe"
    shutil.copy2(built_exe, target_exe)

    size = target_exe.stat().st_size
    sha = hashlib.sha256(target_exe.read_bytes()).hexdigest()
    print(f"--> Windows Executable built: {size:,} bytes | SHA256: {sha}")
    return target_exe


def copy_installer_script() -> Path:
    """Sync installer shell script to downloads directory."""
    print("\n[3/4] Syncing One-Line Installer Script (install.sh)...")
    src = REPO_ROOT / "deploy" / "appliance" / "install.sh"
    dst = DOWNLOADS_DIR / "install.sh"
    shutil.copy2(src, dst)
    size = dst.stat().st_size
    sha = hashlib.sha256(dst.read_bytes()).hexdigest()
    print(f"--> install.sh synced: {size:,} bytes | SHA256: {sha}")
    return dst


def sign_and_verify_release() -> None:
    """Generate Ed25519 cryptographic signature for version.json and verify."""
    print("\n[4/4] Cryptographically Signing Release Manifest (version.json)...")
    from tools.security.release_signer import sign_manifest, verify_manifest

    manifest_file = UPDATES_DIR / "version.json"
    manifest = sign_manifest(
        version=VERSION,
        downloads_dir=DOWNLOADS_DIR,
        output_manifest=manifest_file,
    )
    is_valid = verify_manifest(manifest_file)
    print(f"--> Signature Status: {'[VALID OK]' if is_valid else '[INVALID FAIL]'}")
    if not is_valid:
        raise RuntimeError("Release signature verification failed!")


def main() -> int:
    print(f"====================================================================")
    print(f"         Building ComputeMesh Release v{VERSION} (Windows + Linux)  ")
    print(f"====================================================================")
    build_linux_tarball()
    build_windows_exe()
    copy_installer_script()
    sign_and_verify_release()
    print(f"\n[OK] All release artifacts built, hashed, and signed successfully for v{VERSION}!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
