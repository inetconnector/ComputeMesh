"""ComputeMesh Android APK & AAB Production Build, Signing & Packaging Utility.

Builds Google Play Store compliant artifacts for namespace `com.inetconnector.compumesh`.
Uses Android SDK build-tools, AAPT2 resource compiler, Zipalign, and Apksigner.
Securely signs release artifacts using the production keystore.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
ANDROID_PROJECT_ROOT = REPO_ROOT / "apps" / "android"
PORTAL_DOWNLOADS_DIR = REPO_ROOT / "portal" / "downloads"
KEYSTORE_DIR = Path(r"\\diskstation\Dani\APK-Sign")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Build-Android-APK")


def verify_project_structure() -> bool:
    """Verifies that all required Android app sources, resources, and JNI files exist."""
    required_files = [
        ANDROID_PROJECT_ROOT / "build.gradle.kts",
        ANDROID_PROJECT_ROOT / "settings.gradle.kts",
        ANDROID_PROJECT_ROOT / "app" / "build.gradle.kts",
        ANDROID_PROJECT_ROOT / "app" / "proguard-rules.pro",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "AndroidManifest.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "cpp" / "CMakeLists.txt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "cpp" / "native-lib.cpp",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "java" / "com" / "inetconnector" / "compumesh" / "engine" / "MiniCpmEngine.kt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "java" / "com" / "inetconnector" / "compumesh" / "guard" / "BatteryPolicyGuard.kt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "java" / "com" / "inetconnector" / "compumesh" / "p2p" / "DirectLanDiscovery.kt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "java" / "com" / "inetconnector" / "compumesh" / "service" / "MeshNodeService.kt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "java" / "com" / "inetconnector" / "compumesh" / "server" / "LocalChatServer.kt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "java" / "com" / "inetconnector" / "compumesh" / "ui" / "MainActivity.kt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "java" / "com" / "inetconnector" / "compumesh" / "ui" / "theme" / "Theme.kt",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "drawable" / "ic_launcher_background.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "drawable" / "ic_launcher_foreground.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "drawable" / "ic_stat_computemesh.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "mipmap-anydpi-v26" / "ic_launcher.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "mipmap-anydpi-v26" / "ic_launcher_round.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "values" / "strings.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "values" / "colors.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "values" / "themes.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "xml" / "data_extraction_rules.xml",
        ANDROID_PROJECT_ROOT / "app" / "src" / "main" / "res" / "xml" / "backup_rules.xml",
    ]

    for f in required_files:
        if not f.exists():
            logger.error("Missing required file: %s", f)
            return False
    logger.info("All %d required Android source & resource files verified successfully.", len(required_files))
    return True


def find_android_tools() -> dict[str, Path]:
    """Discovers available Android SDK build-tools and JDK utilities."""
    sdk_root = Path(os.environ.get("ANDROID_HOME", r"C:\Users\frede\AppData\Local\Android\Sdk"))
    tools: dict[str, Path] = {}

    build_tools_dir = sdk_root / "build-tools"
    if build_tools_dir.exists():
        versions = sorted([d for d in build_tools_dir.iterdir() if d.is_dir()], reverse=True)
        for ver_dir in versions:
            aapt2 = ver_dir / "aapt2.exe"
            zipalign = ver_dir / "zipalign.exe"
            apksigner = ver_dir / "apksigner.bat"
            if aapt2.exists() and zipalign.exists() and apksigner.exists():
                tools["aapt2"] = aapt2
                tools["zipalign"] = zipalign
                tools["apksigner"] = apksigner
                tools["build_tools"] = ver_dir
                break

    platforms_dir = sdk_root / "platforms"
    if platforms_dir.exists():
        platforms = sorted([d for d in platforms_dir.iterdir() if d.is_dir()], reverse=True)
        for p in platforms:
            jar = p / "android.jar"
            if jar.exists():
                tools["android_jar"] = jar
                break

    jarsigner = shutil.which("jarsigner")
    if jarsigner:
        tools["jarsigner"] = Path(jarsigner)

    return tools


def find_signing_keystore() -> Optional[Path]:
    """Locates the signing keystore file securely."""
    if KEYSTORE_DIR.exists():
        for f in KEYSTORE_DIR.iterdir():
            if f.is_file() and not f.name.endswith(".json") and f.stat().st_size > 0:
                return f
    return None


def build_and_sign_release() -> tuple[Path, Optional[Path]]:
    """Compiles Android release APK and AAB with Gradle, and signs them using the production keystore."""
    PORTAL_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    target_apk = PORTAL_DOWNLOADS_DIR / "ComputeMesh-Android.apk"
    target_aab = PORTAL_DOWNLOADS_DIR / "ComputeMesh-Android.aab"

    tools = find_android_tools()
    keystore_path = find_signing_keystore()

    gradle_bin = Path(r"C:\Users\frede\.gradle\wrapper\dists\gradle-8.9-bin\90cnw93cvbtalezasaz0blq0a\gradle-8.9\bin\gradle.bat")
    java_home = r"C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot"
    android_home = r"C:\Users\frede\AppData\Local\Android\Sdk"

    env = os.environ.copy()
    env["JAVA_HOME"] = java_home
    env["ANDROID_HOME"] = android_home

    if gradle_bin.exists():
        logger.info("Building production APK & AAB with Gradle: %s", gradle_bin)
        cmd_gradle = [str(gradle_bin), ":app:assembleRelease", ":app:bundleRelease", "--no-daemon"]
        subprocess.run(cmd_gradle, cwd=str(ANDROID_PROJECT_ROOT), env=env, check=True)

        built_apk = ANDROID_PROJECT_ROOT / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
        built_aab = ANDROID_PROJECT_ROOT / "app" / "build" / "outputs" / "bundle" / "release" / "app-release.aab"

        # Sign APK with apksigner
        if keystore_path and "apksigner" in tools and built_apk.exists():
            logger.info("Signing release APK with production keystore (v1, v2, v3)...")
            ks_pass = keystore_path.stem
            cmd_sign = [
                str(tools["apksigner"]), "sign",
                "--ks", str(keystore_path),
                "--ks-pass", f"pass:{ks_pass}",
                "--ks-key-alias", "key0",
                "--min-sdk-version", "29",
                "--v1-signing-enabled", "true",
                "--v2-signing-enabled", "true",
                "--v3-signing-enabled", "true",
                "--out", str(target_apk),
                str(built_apk)
            ]
            subprocess.run(cmd_sign, check=True, capture_output=True)

            cmd_verify = [str(tools["apksigner"]), "verify", "--min-sdk-version", "29", "--verbose", str(target_apk)]
            res_verify = subprocess.run(cmd_verify, check=True, capture_output=True, text=True)
            logger.info("Apksigner verification verified successfully: %s", "Verifies" in res_verify.stdout)
        elif built_apk.exists():
            shutil.copy2(built_apk, target_apk)

        # Sign AAB with jarsigner
        jarsigner = Path(java_home) / "bin" / "jarsigner.exe"
        if keystore_path and jarsigner.exists() and built_aab.exists():
            logger.info("Signing release AAB with jarsigner...")
            shutil.copy2(built_aab, target_aab)
            ks_pass = keystore_path.stem
            cmd_jar = [
                str(jarsigner),
                "-keystore", str(keystore_path),
                "-storepass", ks_pass,
                "-keypass", ks_pass,
                str(target_aab),
                "key0"
            ]
            subprocess.run(cmd_jar, check=True, capture_output=True)
            logger.info("AAB signed successfully.")
        elif built_aab.exists():
            shutil.copy2(built_aab, target_aab)
    else:
        logger.error("Gradle not found.")

    sha256_apk = hashlib.sha256(target_apk.read_bytes()).hexdigest()
    sha256_aab = hashlib.sha256(target_aab.read_bytes()).hexdigest()

    # Read version directly from build.gradle.kts to avoid drift
    gradle_file = ANDROID_PROJECT_ROOT / "app" / "build.gradle.kts"
    v_name = "1.2.155"
    v_code = 115
    if gradle_file.exists():
        content = gradle_file.read_text(encoding="utf-8")
        import re
        m_code = re.search(r'versionCode\s*=\s*(\d+)', content)
        m_name = re.search(r'versionName\s*=\s*"([^"]+)"', content)
        if m_code:
            v_code = int(m_code.group(1))
        if m_name:
            v_name = m_name.group(1)

    metadata = {
        "app_name": "ComputeMesh",
        "package_name": "com.inetconnector.compumesh",
        "version_name": v_name,
        "version_code": v_code,
        "target_sdk": 34,
        "min_sdk": 29,
        "supported_models": ["openbmb/minicpm5-2b"],
        "apk_path": target_apk.relative_to(REPO_ROOT).as_posix(),
        "apk_sha256": sha256_apk,
        "aab_path": target_aab.relative_to(REPO_ROOT).as_posix(),
        "aab_sha256": sha256_aab,
        "signed": keystore_path is not None,
    }

    meta_file = PORTAL_DOWNLOADS_DIR / "ComputeMesh-Android.json"
    meta_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info("Release APK ready: %s (SHA-256: %s)", target_apk, sha256_apk)
    logger.info("Release AAB ready: %s (SHA-256: %s)", target_aab, sha256_aab)
    logger.info("Release Metadata: %s", meta_file)

    return target_apk, target_aab


def main() -> None:
    logger.info("=== Starting ComputeMesh Android Release Build Pipeline ===")
    if not verify_project_structure():
        logger.error("Project structure verification failed.")
        sys.exit(1)

    apk, aab = build_and_sign_release()
    logger.info("=== ComputeMesh Android Build & Sign Complete ===")


if __name__ == "__main__":
    main()
