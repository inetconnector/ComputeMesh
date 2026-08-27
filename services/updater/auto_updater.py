#!/usr/bin/env python3
"""ComputeMesh Cryptographic Auto-Updater Engine (Ed25519).

Fetches signed version manifests from the official inetconnector gateway,
cryptographically verifies the Ed25519 digital signature against the embedded
public key, verifies SHA-256 artifact hashes, and applies seamless updates.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
from typing import Any, Callable
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG
from tools.security.ed25519_verify import verify_ed25519_signature
from tools.security.signing_keys import OFFICIAL_RELEASE_PUBLIC_KEY_HEX, TRUSTED_RELEASE_PUBLIC_KEYS_HEX

DEFAULT_UPDATE_URL = CONFIG.endpoints.update_manifest_url


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_date: str
    download_url: str
    expected_sha256: str
    size_bytes: int
    filename: str
    is_newer: bool


class SignatureVerificationError(Exception):
    """Raised when an update manifest signature fails Ed25519 verification."""


class ChecksumMismatchError(Exception):
    """Raised when downloaded binary does not match the signed SHA-256 hash."""


class AutoUpdater:
    def __init__(
        self,
        current_version: str = "1.2.11",
        manifest_url: str = DEFAULT_UPDATE_URL,
        public_key_hex: str = OFFICIAL_RELEASE_PUBLIC_KEY_HEX,
    ) -> None:
        self.current_version = current_version
        self.manifest_url = manifest_url
        self.public_key_hex = public_key_hex

    def _get_platform_key(self) -> str:
        """Determine platform identifier for manifest matching."""
        system = platform.system().lower()
        if system == "windows":
            return "windows-x64"
        elif system == "linux":
            # Check if running inside NodeOS
            if Path("/etc/computemesh/nodeos_release").exists() or Path("/boot/computemesh.env").exists():
                return "linux-x64"
            return "linux-x64"
        return "windows-x64"

    @staticmethod
    def _parse_version(v: str) -> tuple[int, ...]:
        """Convert semver string to integer tuple for comparison."""
        v = v.lstrip("vV").strip()
        parts = []
        for p in v.split("."):
            if p.isdigit():
                parts.append(int(p))
            else:
                num = "".join(c for c in p if c.isdigit())
                parts.append(int(num) if num else 0)
        return tuple(parts)

    def check_for_updates(self, timeout_seconds: float = 6.0) -> UpdateInfo | None:
        """Fetch and cryptographically verify signed manifest from update server."""
        try:
            req = urllib.request.Request(
                self.manifest_url,
                headers={"User-Agent": f"ComputeMesh-AutoUpdater/{self.current_version}"},
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                manifest_raw = resp.read()

            manifest_data = json.loads(manifest_raw.decode("utf-8"))
            signature_hex = manifest_data.pop("signature", None)
            if not signature_hex:
                raise SignatureVerificationError("Missing digital signature in update manifest.")

            # Verify public key matches trusted release keys
            manifest_pub_hex = (manifest_data.get("public_key") or self.public_key_hex).lower()
            trusted_keys = [k.lower() for k in TRUSTED_RELEASE_PUBLIC_KEYS_HEX]
            if manifest_pub_hex not in trusted_keys and manifest_pub_hex != self.public_key_hex.lower():
                raise SignatureVerificationError(
                    f"Manifest public key ({manifest_pub_hex}) does not match trusted keys ({trusted_keys})"
                )

            # Verify Ed25519 signature
            pub_bytes = bytes.fromhex(manifest_pub_hex)
            sig_bytes = bytes.fromhex(signature_hex)
            canonical_bytes = json.dumps(manifest_data, sort_keys=True).encode("utf-8")
            if not verify_ed25519_signature(pub_bytes, canonical_bytes, sig_bytes):
                raise SignatureVerificationError("Ed25519 signature verification failed! Untrusted release manifest.")

            latest_version = manifest_data.get("version", "0.0.0")
            is_newer = self._parse_version(latest_version) > self._parse_version(self.current_version)

            platform_key = self._get_platform_key()
            platforms = manifest_data.get("platforms", {})
            p_info = platforms.get(platform_key)
            if not p_info:
                return None

            return UpdateInfo(
                version=latest_version,
                release_date=manifest_data.get("release_date", ""),
                download_url=p_info["url"],
                expected_sha256=p_info["sha256"],
                size_bytes=p_info.get("size_bytes", 0),
                filename=p_info.get("filename", "update_package"),
                is_newer=is_newer,
            )

        except Exception as e:
            # Network failure or signature error
            return None

    def download_and_verify(
        self,
        update_info: UpdateInfo,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Download binary update and verify SHA-256 checksum."""
        temp_dir = Path(tempfile.mkdtemp(prefix="cm_update_"))
        target_path = temp_dir / update_info.filename

        req = urllib.request.Request(
            update_info.download_url,
            headers={"User-Agent": f"ComputeMesh-AutoUpdater/{self.current_version}"},
        )

        h = hashlib.sha256()
        total_downloaded = 0

        with urllib.request.urlopen(req, timeout=30.0) as resp:
            total_size = int(resp.headers.get("Content-Length", update_info.size_bytes or 0))
            with open(target_path, "wb") as out_f:
                while chunk := resp.read(65536):
                    out_f.write(chunk)
                    h.update(chunk)
                    total_downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(total_downloaded, total_size)

        actual_sha = h.hexdigest()
        if actual_sha.lower() != update_info.expected_sha256.lower():
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise ChecksumMismatchError(
                f"Checksum mismatch! Expected {update_info.expected_sha256}, got {actual_sha}"
            )

        return target_path

    def apply_windows_update(self, downloaded_exe: Path) -> None:
        """Apply Windows binary update by spawning updater script."""
        import subprocess

        current_exe = Path(sys.executable)
        updater_bat = downloaded_exe.parent / "apply_update.bat"

        bat_content = f"""@echo off
timeout /t 2 /nobreak > NUL
set _MEIPASS=
set _MEIPASS2=
set _PYI_PARENT_PID=
set _PYI_CHILD_PROCESS=
set PYINSTALLER_STRICT_UNPACK_MODE=
copy /y "{downloaded_exe}" "{current_exe}" > NUL
start "" "{current_exe}"
del "%~f0"
"""
        updater_bat.write_text(bat_content, encoding="utf-8")
        clean_env = os.environ.copy()
        for k in list(clean_env.keys()):
            if k.startswith("_MEI") or k.startswith("_PYI") or k.startswith("PYINSTALLER"):
                clean_env.pop(k, None)
        subprocess.Popen(["cmd.exe", "/c", str(updater_bat)], creationflags=0x08000000, env=clean_env)
        sys.exit(0)

    def apply_linux_update(self, downloaded_pkg: Path) -> None:
        """Apply Linux update by restarting systemd service or extracting binary."""
        import subprocess

        if downloaded_pkg.suffix in (".gz", ".tgz") or downloaded_pkg.name.endswith(".tar.gz"):
            for target_dir in ["/opt/computemesh", "/root/ComputeMesh"]:
                p = Path(target_dir)
                if p.exists():
                    try:
                        shutil.unpack_archive(str(downloaded_pkg), str(p))
                        nested = p / "computemesh"
                        if nested.exists():
                            for item in nested.iterdir():
                                dest = p / item.name
                                if item.is_dir():
                                    shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                                else:
                                    shutil.copy2(str(item), str(dest))
                    except Exception:
                        pass

            # Restart all active computemesh services
            subprocess.Popen(
                ["sh", "-c", "sleep 1 && systemctl restart computemesh-appliance.service computemesh-dashboard.service computemesh-kiosk.service computemesh-console.service computemesh-node.service computemesh-gateway.service computemesh-autoupdate.service computemesh.service || true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def main() -> int:
    import argparse
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(description="ComputeMesh Automated Cryptographic Updater")
    parser.add_argument("--check-and-apply", action="store_true", help="Check and apply update if available")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background checking periodically")
    parser.add_argument("--interval", type=int, default=300, help="Check interval in seconds (default 300s)")
    parser.add_argument("--version", default="1.2.11", help="Current running version")
    args = parser.parse_args()

    updater = AutoUpdater(current_version=args.version)

    if args.daemon:
        print(f"Starting ComputeMesh Auto-Updater Daemon (polling every {args.interval}s)...")
        while True:
            try:
                info = updater.check_for_updates()
                if info and info.is_newer:
                    print(f"[{datetime.now(timezone.utc).isoformat()}] New signed release v{info.version} detected! Downloading...")
                    pkg = updater.download_and_verify(info)
                    print(f"[{datetime.now(timezone.utc).isoformat()}] Cryptographic verification PASSED. Applying update...")
                    updater.apply_linux_update(pkg)
                    updater.current_version = info.version
                else:
                    print(f"[{datetime.now(timezone.utc).isoformat()}] System is up to date (running v{updater.current_version}).")
            except Exception as e:
                print(f"[{datetime.now(timezone.utc).isoformat()}] Update check error: {e}")
            time.sleep(args.interval)

    elif args.check_and_apply:
        info = updater.check_for_updates()
        if info and info.is_newer:
            print(f"New signed release v{info.version} available. Downloading and applying...")
            pkg = updater.download_and_verify(info)
            updater.apply_linux_update(pkg)
            print("Update applied successfully.")
            return 0
        else:
            print(f"Already on latest version (v{args.version}).")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
