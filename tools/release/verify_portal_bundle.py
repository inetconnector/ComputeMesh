#!/usr/bin/env python3
"""Fail-closed ComputeMesh multi-platform release gate.

Run inside a clean checkout of the exact *tagged commit*, with all signed
artifacts staged under portal/downloads. Never creates tags, keys or releases.
This script never downloads unsigned installers or rewrites signed manifests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = {
    "windows-x64": "ComputeMesh-Setup-x64.exe",
    "linux-x64": "computemesh-linux-x86_64.tar.gz",
    "nodeos-iso": "computemesh-nodeos-x86_64.iso",
    "nodeos-img": "computemesh-nodeos-x86_64.img.xz",
    "nodeos-runtime-x64": "computemesh-nodeos-runtime-x86_64.tar.gz",
    "installer-script": "install.sh",
}
ANDROID_FILES = ("ComputeMesh-Android.apk", "ComputeMesh-Android.aab", "ComputeMesh-Android.json")
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+(?:-rc\.\d+)?)$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
HOST = "mesh.inetconnector.com"


class ReleaseGateError(Exception):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def valid_artifact(
    directory: Path, filename: str, digest: object, size: object, url: object,
) -> dict:
    if (not isinstance(filename, str) or
            not re.fullmatch(r"[a-zA-Z0-9_.-]{2,130}", filename)):
        raise ReleaseGateError("unsafe artifact filename")
    target = directory / filename
    if target.is_symlink() or not target.is_file():
        raise ReleaseGateError(f"missing artifact: {filename}")
    actual_size = target.stat().st_size
    if not isinstance(size, int) or size <= 0 or size != actual_size:
        raise ReleaseGateError(f"size mismatch: {filename}")
    if not isinstance(digest, str) or not HEX_RE.fullmatch(digest.lower()):
        raise ReleaseGateError(f"invalid SHA256: {filename}")
    if sha256(target) != digest.lower():
        raise ReleaseGateError(f"SHA256 mismatch: {filename}")
    expected_url = f"https://{HOST}/downloads/{filename}"
    if url != expected_url:
        raise ReleaseGateError(f"untrusted download URL: {filename}")
    return {"filename": filename, "sha256": digest, "size_bytes": size, "url": url}


def verify_release(root: Path, tag: str, *, artifacts_dir: Path | None = None) -> dict:
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise ReleaseGateError("release tag must be vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-rc.N")
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ReleaseGateError("release checkout contains uncommitted changes")
    head = git(root, "rev-parse", "HEAD")
    if tag not in git(root, "tag", "--points-at", "HEAD").splitlines():
        raise ReleaseGateError("tag does not point at the checked-out commit")

    from tools.security.release_signer import verify_manifest

    portal = root / "portal"
    downloads = artifacts_dir or portal / "downloads"
    manifest_file = portal / "updates" / "version.json"
    if not verify_manifest(manifest_file):
        raise ReleaseGateError("release manifest signature missing/invalid/untrusted")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("version") != match.group(1):
        raise ReleaseGateError("release tag and signed manifest version disagree")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict):
        raise ReleaseGateError("signed manifest has no platforms")
    checked = {}
    for platform, filename in REQUIRED.items():
        item = platforms.get(platform)
        if not isinstance(item, dict) or item.get("filename") != filename:
            raise ReleaseGateError(f"missing signed platform: {platform}")
        checked[platform] = valid_artifact(
            downloads, filename, item.get("sha256"),
            item.get("size_bytes"), item.get("url"),
        )

    android_path = downloads / ANDROID_FILES[2]
    if android_path.is_symlink() or not android_path.is_file():
        raise ReleaseGateError("Android release manifest missing")
    android = json.loads(android_path.read_text(encoding="utf-8"))
    if android.get("production_signed") is not True:
        raise ReleaseGateError("Android APK is not marked production-signed")
    if android.get("package_name") != "com.inetconnector.compumesh":
        raise ReleaseGateError("Android package name mismatch")
    android_version = android.get("version_name", android.get("version"))
    if not isinstance(android_version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", android_version):
        raise ReleaseGateError("Android version is missing/invalid")
    checked["android-apk"] = valid_artifact(
        downloads, ANDROID_FILES[0],
        android.get("apk_sha256"), android.get("apk_size"), android.get("url"),
    )
    checked["android-aab"] = valid_artifact(
        downloads, ANDROID_FILES[1],
        android.get("aab_sha256"), android.get("aab_size"), android.get("aab_url"),
    )
    # Two accepted routes to /downloads must display identical version/links.
    if (portal / "downloads.html").read_bytes() != (downloads / "index.html").read_bytes():
        raise ReleaseGateError("downloads.html and downloads/index.html have diverged")
    for name in ANDROID_FILES[:2]:
        if not (downloads / name).is_file():
            raise ReleaseGateError(f"Android asset absent: {name}")
    # Source HTML may not claim a different frozen artifact version.
    download_page = (portal / "downloads.html").read_text(encoding="utf-8")
    if not all(f'/downloads/{name}' in download_page for name in
               (REQUIRED["windows-x64"], REQUIRED["installer-script"], ANDROID_FILES[0])):
        raise ReleaseGateError("download navigation is missing a required installer")
    return {
        "schema": 1,
        "tag": tag,
        "commit": head,
        "portal_version": manifest["version"],
        "android_version": android_version,
        "artifacts": checked,
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_release(args.repo_root.resolve(), args.tag,
                                artifacts_dir=args.artifacts_dir.resolve() if args.artifacts_dir else None)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"result": "PASS", "tag": result["tag"], "commit": result["commit"],
                          "assets": len(result["artifacts"])}, sort_keys=True))
        return 0
    except (ReleaseGateError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print("RELEASE_NO_GO:", type(exc).__name__, str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
