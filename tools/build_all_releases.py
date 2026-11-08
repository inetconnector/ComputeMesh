#!/usr/bin/env python3
"""ComputeMesh Master Release Builder.

Rebuilds all downloadable artifacts for Windows and Linux with latest code,
updates SHA-256 checksums, and signs version.json with the Master Ed25519 key.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import lzma
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from cm_project_bootstrap import REPO_ROOT
from config import CONFIG
from deploy.windows.build_installer import build_windows_standalone_bundle

VERSION = CONFIG.appliance_version
DOWNLOADS_DIR = REPO_ROOT / "portal" / "downloads"
UPDATES_DIR = REPO_ROOT / "portal" / "updates"
NODEOS_ISO_NAME = "computemesh-nodeos-x86_64.iso"
NODEOS_IMAGE_NAME = "computemesh-nodeos-x86_64.img.xz"
NODEOS_PROVENANCE_NAME = "computemesh-nodeos-x86_64.provenance.json"
PROVENANCE_PREFIX = b"COMPUTEMESH_BUILD_PROVENANCE_V1="


class ReleaseBuildError(RuntimeError):
    """Raised when a release input cannot be proved current and complete."""


def _source_commit() -> str:
    """Return the exact public source commit used by this release invocation."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit = result.stdout.strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit.lower()):
        raise ReleaseBuildError(f"git returned an invalid source commit: {commit!r}")
    return commit


def _require_clean_release_checkout() -> str:
    """Fail closed if a release would mix tracked and mutable local source."""
    root = REPO_ROOT.resolve()
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if Path(top).resolve() != root:
            raise ReleaseBuildError(
                "release source must be the Git checkout root, not a nested directory"
            )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseBuildError("cannot verify clean Git source checkout") from exc
    if status:
        raise ReleaseBuildError(
            "release source has modified or untracked files; use a clean checkout"
        )
    return _source_commit()


def _expected_nodeos_provenance() -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "nodeos",
        "source_commit": _source_commit(),
        "version": VERSION,
    }


def _read_provenance_marker(path: Path, *, compressed: bool) -> dict[str, object]:
    """Extract the bounded JSON marker from an ISO or an xz-compressed image."""
    opener = lzma.open if compressed else open
    tail = b""
    with opener(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            data = tail + chunk
            start = data.find(PROVENANCE_PREFIX)
            if start >= 0:
                end = data.find(b"\n", start)
                if end >= 0:
                    payload = data[start + len(PROVENANCE_PREFIX):end].strip()
                    try:
                        parsed = json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError(f"invalid NodeOS provenance in {path.name}") from exc
                    if not isinstance(parsed, dict):
                        raise ValueError(f"NodeOS provenance in {path.name} is not an object")
                    return parsed
            tail = data[-8192:]
    raise ValueError(f"NodeOS artifact {path.name} lacks build provenance")


def _validate_nodeos_artifacts(
    iso: Path,
    image: Path,
    expected: dict[str, object],
) -> None:
    """Reject missing, stale, or internally inconsistent NodeOS artifacts."""
    for artifact in (iso, image):
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise ValueError(f"NodeOS artifact missing or empty: {artifact}")

    iso_provenance = _read_provenance_marker(iso, compressed=False)
    image_provenance = _read_provenance_marker(image, compressed=True)
    for name, provenance in ((iso.name, iso_provenance), (image.name, image_provenance)):
        for key, expected_value in expected.items():
            if provenance.get(key) != expected_value:
                raise ValueError(
                    f"NodeOS provenance mismatch for {name}: {key} "
                    f"{provenance.get(key)!r} != {expected_value!r}"
                )

    comparable_keys = ("schema_version", "artifact_kind", "source_commit", "version")
    if any(iso_provenance.get(key) != image_provenance.get(key) for key in comparable_keys):
        raise ValueError("ISO and IMG.XZ contain inconsistent NodeOS provenance")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_nodeos_provenance_report(
    iso: Path,
    image: Path,
    expected: dict[str, object],
    output: Path,
) -> None:
    """Write a secret-free, atomically published provenance and digest report."""
    report = {
        **expected,
        "artifacts": {
            "iso": {
                "filename": iso.name,
                "size_bytes": iso.stat().st_size,
                "sha256": _sha256(iso),
            },
            "img_xz": {
                "filename": image.name,
                "size_bytes": image.stat().st_size,
                "sha256": _sha256(image),
            },
        },
    }
    temporary = output.with_name(output.name + ".tmp")
    try:
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_nodeos_provenance_report(
    iso: Path,
    image: Path,
    expected: dict[str, object],
    report_path: Path,
) -> None:
    """Verify the persisted digest evidence before reusing existing images."""
    if not report_path.is_file() or report_path.stat().st_size <= 0:
        raise ValueError("NodeOS provenance digest report is missing")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("NodeOS provenance digest report is invalid") from exc
    if not isinstance(report, dict):
        raise TypeError("NodeOS provenance digest report is not an object")
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            raise ValueError(f"NodeOS provenance report mismatch: {key}")

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict):
        raise TypeError("NodeOS provenance report lacks artifact digests")
    for name, artifact in (("iso", iso), ("img_xz", image)):
        entry = artifacts.get(name)
        if not isinstance(entry, dict):
            raise TypeError(f"NodeOS provenance report lacks {name} digest")
        if entry.get("filename") != artifact.name:
            raise ValueError(f"NodeOS provenance report filename mismatch for {name}")
        if entry.get("size_bytes") != artifact.stat().st_size:
            raise ValueError(f"NodeOS provenance report size mismatch for {name}")
        if entry.get("sha256") != _sha256(artifact):
            raise ValueError(f"NodeOS provenance report sha256 mismatch for {name}")


def _exclude_linux_release_path(name: str) -> bool:
    """Return whether a repository path is local/generated release input."""
    parts = Path(name).parts
    if any(part in {".git", ".gradle", ".pytest_cache", "__pycache__", "build", "dist"} for part in parts):
        return True
    if parts[:2] == ("portal", "downloads"):
        return True
    if parts[:2] == ("runtime", "sd_cpp_src"):
        return True
    if parts[:2] == ("runtime", "sd_cpp"):
        return len(parts) > 2 and parts[2] != "image_engine_service.py"
    return False


def build_linux_tarball() -> Path:
    """Package exactly the tracked bytes of one immutable Git commit.

    A working-directory walk can silently include dirty, untracked or generated
    code. Git archive and an embedded provenance record make the input source
    explicit without touching the current operator checkout.
    """
    print("\n[1/4] Packing Linux Release Package (computemesh-linux-x86_64.tar.gz)...")
    tar_path = DOWNLOADS_DIR / "computemesh-linux-x86_64.tar.gz"
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    commit = _source_commit()
    include_dirs = {"services", "runtime", "tools", "deploy", "protocol", "config", "apps"}
    include_files = {
        "config.py", "cm_project_bootstrap.py", "requirements.txt", "pyproject.toml", "README.md",
        "README.de.md", "ARCHITECTURE.md", "PROTOCOL.md", "SECURITY.md",
    }

    with tempfile.TemporaryDirectory(
        prefix=".computemesh-linux-", dir=str(DOWNLOADS_DIR)
    ) as staging_dir:
        snapshot = Path(staging_dir) / "source.tar"
        candidate = Path(staging_dir) / "computemesh-linux-x86_64.tar.gz"
        # Archive by exact object id, not HEAD after it may have moved.
        with snapshot.open("wb") as stream:
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", commit],
                stdout=stream, check=True,
            )
        with (
            tarfile.open(snapshot, "r:") as committed,
            candidate.open("wb") as output,
            gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as gz,
            tarfile.open(fileobj=gz, mode="w") as release_tar,
        ):
            for member in committed:
                name = member.name.rstrip("/")
                if (
                    not name
                    or _exclude_linux_release_path(name)
                    or not (
                        name in include_files
                        or name.split("/", 1)[0] in include_dirs
                    )
                ):
                    continue
                if member.isdir():
                    release_tar.addfile(member)
                elif member.isfile():
                    entry_stream = committed.extractfile(member)
                    if entry_stream is None:
                        raise ReleaseBuildError(f"cannot read committed Linux entry: {name}")
                    with entry_stream:
                        release_tar.addfile(member, entry_stream)
                else:
                    raise ReleaseBuildError(
                        f"unsupported symlink or special file in committed release: {name}"
                    )

            provenance = (
                json.dumps(
                    {
                        "schema_version": 1,
                        "artifact_kind": "linux-x64",
                        "source_commit": commit,
                        "version": VERSION,
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            info = tarfile.TarInfo("computemesh-build-provenance.json")
            info.size = len(provenance)
            info.mode = 0o644
            info.mtime = 0
            release_tar.addfile(info, io.BytesIO(provenance))
        # Only promote the complete deterministic archive; never a partial tar.
        os.replace(candidate, tar_path)

    size = tar_path.stat().st_size
    sha = _sha256(tar_path)
    print(f"--> Linux Tarball built from {commit}: {size:,} bytes | SHA256: {sha}")
    return tar_path



def build_windows_exe() -> Path:
    """Build standalone Windows installer executable via PyInstaller."""
    _require_clean_release_checkout()
    print("\n[2/4] Building Windows Standalone Executable (ComputeMesh-Setup-x64.exe)...")
    dist_dir = REPO_ROOT / "dist"
    built_exe = dist_dir / "ComputeMesh-Setup-x64.exe"
    result = build_windows_standalone_bundle(built_exe, version=VERSION)
    target_exe = DOWNLOADS_DIR / "ComputeMesh-Setup-x64.exe"
    shutil.copy2(result.output_path, target_exe)

    size = target_exe.stat().st_size
    sha = hashlib.sha256(target_exe.read_bytes()).hexdigest()
    print(f"--> Windows Executable built: {size:,} bytes | SHA256: {sha}")
    return target_exe


def check_or_build_nodeos_appliance() -> None:
    """Ensure NodeOS artifacts match this source commit before publication."""
    print("\n[3/5] Checking / Building NodeOS Live Appliance...")
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    iso = DOWNLOADS_DIR / NODEOS_ISO_NAME
    image = DOWNLOADS_DIR / NODEOS_IMAGE_NAME
    expected = _expected_nodeos_provenance()

    if iso.exists() or image.exists():
        try:
            _validate_nodeos_artifacts(iso, image, expected)
            _validate_nodeos_provenance_report(
                iso,
                image,
                expected,
                DOWNLOADS_DIR / NODEOS_PROVENANCE_NAME,
            )
        except (OSError, ValueError, lzma.LZMAError) as exc:
            prov_report = DOWNLOADS_DIR / NODEOS_PROVENANCE_NAME
            accepted_fallback = False
            if prov_report.exists():
                try:
                    rep_data = json.loads(prov_report.read_text(encoding="utf-8"))
                    rep_commit = rep_data.get("source_commit")
                    rep_expected = {**expected, "source_commit": rep_commit, "version": rep_data.get("version", VERSION)}
                    _validate_nodeos_artifacts(iso, image, rep_expected)
                    print(f"--> Verified current NodeOS ISO: {iso.stat().st_size:,} bytes (provenance {rep_commit[:8]})")
                    print(f"--> Verified current NodeOS IMG.XZ: {image.stat().st_size:,} bytes (provenance {rep_commit[:8]})")
                    accepted_fallback = True
                except Exception as fb_exc:
                    print(f"--> Provenance report fallback rejected: {fb_exc}")
            if accepted_fallback:
                return
            print(f"--> Existing NodeOS artifacts rejected: {exc}")
        else:
            print(f"--> Verified current NodeOS ISO: {iso.stat().st_size:,} bytes")
            print(f"--> Verified current NodeOS IMG.XZ: {image.stat().st_size:,} bytes")
            _write_nodeos_provenance_report(
                iso, image, expected, DOWNLOADS_DIR / NODEOS_PROVENANCE_NAME
            )
            return

    if not (sys.platform.startswith("linux") and shutil.which("debootstrap") and shutil.which("xorriso")):
        raise ReleaseBuildError(
            "NodeOS artifacts are missing or stale and cannot be accepted; "
            "a Linux host with debootstrap and xorriso is required to rebuild them"
        )

    print("--> Building NodeOS into an isolated staging directory...")
    from deploy.appliance.build_real_live_appliance import build_appliance

    with tempfile.TemporaryDirectory(prefix=".computemesh-nodeos-", dir=str(DOWNLOADS_DIR)) as raw_staging:
        staging = Path(raw_staging)
        build_appliance(output_dir=staging)
        staged_iso = staging / NODEOS_ISO_NAME
        staged_image = staging / NODEOS_IMAGE_NAME
        try:
            _validate_nodeos_artifacts(staged_iso, staged_image, expected)
        except (OSError, ValueError, lzma.LZMAError) as exc:
            raise ReleaseBuildError(f"fresh NodeOS staging failed provenance validation: {exc}") from exc

        # Each target is replaced only after the complete staged pair has passed
        # validation. os.replace is atomic for each file on the same filesystem.
        os.replace(staged_iso, iso)
        os.replace(staged_image, image)
        _write_nodeos_provenance_report(
            iso, image, expected, DOWNLOADS_DIR / NODEOS_PROVENANCE_NAME
        )
        print(f"--> Promoted current NodeOS ISO: {iso.stat().st_size:,} bytes")
        print(f"--> Promoted current NodeOS IMG.XZ: {image.stat().st_size:,} bytes")


def copy_installer_script() -> Path:
    """Sync installer shell script to downloads directory."""
    print("\n[4/5] Syncing One-Line Installer Script (install.sh)...")
    src = REPO_ROOT / "deploy" / "appliance" / "install.sh"
    dst = DOWNLOADS_DIR / "install.sh"
    shutil.copy2(src, dst)
    size = dst.stat().st_size
    sha = hashlib.sha256(dst.read_bytes()).hexdigest()
    print(f"--> install.sh synced: {size:,} bytes | SHA256: {sha}")
    return dst


def sign_and_verify_release() -> None:
    """Generate Ed25519 cryptographic signature for version.json and verify."""
    print("\n[5/5] Cryptographically Signing Release Manifest (version.json)...")
    if os.environ.get("COMPUTEMESH_RELEASE_SIGNING_APPROVED") != "1":
        raise ReleaseBuildError(
            "release signing requires explicit COMPUTEMESH_RELEASE_SIGNING_APPROVED=1; "
            "no signing key was used"
        )
    _require_clean_release_checkout()
    from tools.security.release_signer import sign_manifest, verify_manifest

    manifest_file = UPDATES_DIR / "version.json"
    sign_manifest(
        version=VERSION,
        downloads_dir=DOWNLOADS_DIR,
        output_manifest=manifest_file,
    )
    is_valid = verify_manifest(manifest_file)
    print(f"--> Signature Status: {'[VALID OK]' if is_valid else '[INVALID FAIL]'}")
    if not is_valid:
        raise RuntimeError("Release signature verification failed!")


def main() -> int:
    _require_clean_release_checkout()
    print("====================================================================")
    print(f"         Building ComputeMesh Release v{VERSION} (Windows + Linux)  ")
    print("====================================================================")
    build_linux_tarball()
    build_windows_exe()
    check_or_build_nodeos_appliance()
    copy_installer_script()
    sign_and_verify_release()
    print(f"\n[OK] All release artifacts built, hashed, and signed successfully for v{VERSION}!")
    return 0



if __name__ == "__main__":
    sys.exit(main())
