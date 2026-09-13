"""Build and package the signed ComputeMesh Android release.

The Gradle project owns signing. Production builds require these environment
variables (enforced in app/build.gradle.kts):

- CM_ANDROID_KEYSTORE_PATH
- CM_ANDROID_KEYSTORE_PASSWORD
- CM_ANDROID_KEY_ALIAS
- CM_ANDROID_KEY_PASSWORD

For local non-distribution testing only, CM_ANDROID_ALLOW_DEBUG_RELEASE=1 may
be used. Generated APK/AAB/metadata are copied to portal/downloads and are
ignored by git; the production release workflow publishes them as release
assets and deployment synchronizes those verified assets to the web server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_ROOT = REPO_ROOT / "apps" / "android"
APP_GRADLE = ANDROID_ROOT / "app" / "build.gradle.kts"
PORTAL_DOWNLOADS = REPO_ROOT / "portal" / "downloads"
PUBLIC_BASE = "https://mesh.inetconnector.com/downloads"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("computemesh.android.release")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gradle_wrapper() -> Path:
    wrapper = ANDROID_ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not wrapper.exists():
        raise FileNotFoundError(f"Gradle wrapper not found: {wrapper}")
    if os.name != "nt":
        wrapper.chmod(wrapper.stat().st_mode | 0o111)
    return wrapper


def _read_version() -> tuple[str, int]:
    text = APP_GRADLE.read_text(encoding="utf-8")
    name_match = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    code_match = re.search(r"versionCode\s*=\s*(\d+)", text)
    if not name_match or not code_match:
        raise RuntimeError("Could not read Android versionName/versionCode")
    return name_match.group(1), int(code_match.group(1))


def _verify_signing_environment() -> None:
    if os.environ.get("CM_ANDROID_ALLOW_DEBUG_RELEASE") == "1":
        log.warning("Building a DEBUG-SIGNED release for local testing only; do not publish it.")
        return
    required = (
        "CM_ANDROID_KEYSTORE_PATH",
        "CM_ANDROID_KEYSTORE_PASSWORD",
        "CM_ANDROID_KEY_ALIAS",
        "CM_ANDROID_KEY_PASSWORD",
    )
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("Production Android signing is not configured: " + ", ".join(missing))
    keystore = Path(os.environ["CM_ANDROID_KEYSTORE_PATH"])
    if not keystore.is_file() or keystore.stat().st_size == 0:
        raise RuntimeError(f"Android keystore is missing or empty: {keystore}")


def _find_apksigner() -> Path | None:
    executable = "apksigner.bat" if os.name == "nt" else "apksigner"
    direct = shutil.which(executable)
    if direct:
        return Path(direct)
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        return None
    build_tools = Path(sdk) / "build-tools"
    if not build_tools.exists():
        return None
    for version_dir in sorted(build_tools.iterdir(), reverse=True):
        candidate = version_dir / executable
        if candidate.exists():
            return candidate
    return None


def build_release() -> tuple[Path, Path, Path]:
    _verify_signing_environment()
    wrapper = _gradle_wrapper()
    log.info("Building Android APK and AAB with Gradle wrapper")
    subprocess.run(
        [str(wrapper), "--no-daemon", "--stacktrace", ":app:assembleRelease", ":app:bundleRelease"],
        cwd=ANDROID_ROOT,
        env=os.environ.copy(),
        check=True,
    )

    built_apk = ANDROID_ROOT / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
    built_aab = ANDROID_ROOT / "app" / "build" / "outputs" / "bundle" / "release" / "app-release.aab"
    for path in (built_apk, built_aab):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Expected Android build artifact is missing: {path}")

    apksigner = _find_apksigner()
    if apksigner and os.environ.get("CM_ANDROID_ALLOW_DEBUG_RELEASE") != "1":
        subprocess.run([str(apksigner), "verify", "--verbose", "--print-certs", str(built_apk)], check=True)

    jarsigner = shutil.which("jarsigner")
    if jarsigner and os.environ.get("CM_ANDROID_ALLOW_DEBUG_RELEASE") != "1":
        subprocess.run([jarsigner, "-verify", "-strict", str(built_aab)], check=True)

    PORTAL_DOWNLOADS.mkdir(parents=True, exist_ok=True)
    target_apk = PORTAL_DOWNLOADS / "ComputeMesh-Android.apk"
    target_aab = PORTAL_DOWNLOADS / "ComputeMesh-Android.aab"
    shutil.copy2(built_apk, target_apk)
    shutil.copy2(built_aab, target_aab)

    version_name, version_code = _read_version()
    metadata = {
        "app_name": "ComputeMesh",
        "package_name": "com.inetconnector.compumesh",
        "version": version_name,
        "version_name": version_name,
        "versionCode": version_code,
        "version_code": version_code,
        "min_sdk": 29,
        "target_sdk": 34,
        "sha256": _sha256(target_apk),
        "apk_sha256": _sha256(target_apk),
        "size": target_apk.stat().st_size,
        "apk_size": target_apk.stat().st_size,
        "aab_sha256": _sha256(target_aab),
        "aab_size": target_aab.stat().st_size,
        "url": f"{PUBLIC_BASE}/ComputeMesh-Android.apk",
        "aab_url": f"{PUBLIC_BASE}/ComputeMesh-Android.aab",
        "github_release_tag": "android-latest",
        "production_signed": os.environ.get("CM_ANDROID_ALLOW_DEBUG_RELEASE") != "1",
    }
    metadata_path = PORTAL_DOWNLOADS / "ComputeMesh-Android.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    log.info("APK: %s (%s)", target_apk, metadata["apk_sha256"])
    log.info("AAB: %s (%s)", target_aab, metadata["aab_sha256"])
    log.info("Metadata: %s", metadata_path)
    return target_apk, target_aab, metadata_path


def main() -> int:
    try:
        build_release()
    except Exception as exc:
        log.error("Android release build failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
