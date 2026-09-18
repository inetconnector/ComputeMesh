# SPDX-License-Identifier: Apache-2.0
"""Android & Google Play Store Automation Tools for ComputeMesh Agentic Engineering."""

from __future__ import annotations

import json
import logging
import os
import re
import struct
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("computemesh.mcp.android_play_store")

# Google Play Policy Limits
MAX_TITLE_LENGTH = 30
MAX_SHORT_DESC_LENGTH = 80
MAX_FULL_DESC_LENGTH = 4000

PROHIBITED_TERMS = [
    r"\b#1\b",
    r"\bbest(?:e[srn]?)?\s+(?:app|tool|kiosk)\b",
    r"\btop\s+(?:app|rated|downloads)\b",
    r"\bfree\s+download\s+now\b",
    r"\b100%\s+free\b",
    r"\bguaranteed\b",
]


def _get_image_dimensions_pure_python(file_path: Path) -> Optional[Tuple[int, int]]:
    """Reads PNG or JPEG dimensions without requiring PIL/Pillow."""
    try:
        with open(file_path, "rb") as f:
            data = f.read(32)
            # PNG signature: 89 50 4E 47 0D 0A 1A 0A
            if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
                # IHDR width at offset 16 (4 bytes), height at offset 20 (4 bytes)
                w, h = struct.unpack(">II", data[16:24])
                return int(w), int(h)
            # JPEG signature: FF D8
            if data.startswith(b"\xff\xd8"):
                f.seek(0)
                full_data = f.read()
                size = len(full_data)
                idx = 2
                while idx < size:
                    while idx < size and full_data[idx] != 0xFF:
                        idx += 1
                    while idx < size and full_data[idx] == 0xFF:
                        idx += 1
                    if idx >= size:
                        break
                    marker = full_data[idx]
                    idx += 1
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        if idx + 7 <= size:
                            _, h, w = struct.unpack(">BHH", full_data[idx + 2 : idx + 7])
                            return int(w), int(h)
                    elif marker in (0xD9, 0xDA):
                        break
                    else:
                        if idx + 2 <= size:
                            length = struct.unpack(">H", full_data[idx : idx + 2])[0]
                            idx += length
    except Exception as exc:
        log.debug("Image dimension extraction error for %s: %s", file_path, exc)
    return None


def validate_store_listing(
    title: str,
    short_description: str,
    full_description: str,
    check_prohibited_terms: bool = True,
) -> Dict[str, Any]:
    """Validates Google Play Store text listing against official character bounds and policy guidelines."""
    t_clean = str(title or "").strip()
    s_clean = str(short_description or "").strip()
    f_clean = str(full_description or "").strip()

    errors: List[str] = []
    warnings: List[str] = []

    # Length checks
    t_len = len(t_clean)
    s_len = len(s_clean)
    f_len = len(f_clean)

    if t_len == 0:
        errors.append("Title is required and cannot be empty.")
    elif t_len > MAX_TITLE_LENGTH:
        errors.append(f"Title exceeds Google Play limit ({t_len}/{MAX_TITLE_LENGTH} characters).")

    if s_len == 0:
        errors.append("Short description is required and cannot be empty.")
    elif s_len > MAX_SHORT_DESC_LENGTH:
        errors.append(f"Short description exceeds limit ({s_len}/{MAX_SHORT_DESC_LENGTH} characters).")

    if f_len == 0:
        errors.append("Full description is required and cannot be empty.")
    elif f_len > MAX_FULL_DESC_LENGTH:
        errors.append(f"Full description exceeds limit ({f_len}/{MAX_FULL_DESC_LENGTH} characters).")

    # Policy checks for spammy / misleading words
    if check_prohibited_terms:
        for pat in PROHIBITED_TERMS:
            if re.search(pat, t_clean, re.IGNORECASE):
                warnings.append(f"Title contains potentially non-compliant marketing phrase matching '{pat}'.")
            if re.search(pat, s_clean, re.IGNORECASE):
                warnings.append(f"Short description contains potentially non-compliant marketing phrase matching '{pat}'.")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "title_length": t_len,
            "title_max": MAX_TITLE_LENGTH,
            "short_desc_length": s_len,
            "short_desc_max": MAX_SHORT_DESC_LENGTH,
            "full_desc_length": f_len,
            "full_desc_max": MAX_FULL_DESC_LENGTH,
        },
    }


def validate_store_graphics(
    icon_path: Optional[str] = None,
    feature_graphic_path: Optional[str] = None,
    screenshots_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Validates app icons (512x512 PNG), feature graphics (1024x500 PNG/JPEG) and screenshot sets."""
    results: Dict[str, Any] = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "assets": {},
    }

    # Validate Icon
    if icon_path:
        p = Path(icon_path).resolve()
        if not p.is_file():
            results["valid"] = False
            results["errors"].append(f"App Icon not found at '{icon_path}'.")
        else:
            sz_kb = p.stat().st_size / 1024.0
            dims = _get_image_dimensions_pure_python(p)
            icon_info = {"file": str(p), "size_kb": round(sz_kb, 1), "dimensions": dims}
            if sz_kb > 1024:
                results["valid"] = False
                results["errors"].append(f"App Icon is too large ({sz_kb:.1f} KB, max: 1024 KB).")
            if dims and (dims[0] != 512 or dims[1] != 512):
                results["valid"] = False
                results["errors"].append(f"App Icon dimensions must be exactly 512x512 (found: {dims[0]}x{dims[1]}).")
            results["assets"]["icon"] = icon_info

    # Validate Feature Graphic
    if feature_graphic_path:
        p = Path(feature_graphic_path).resolve()
        if not p.is_file():
            results["valid"] = False
            results["errors"].append(f"Feature Graphic not found at '{feature_graphic_path}'.")
        else:
            sz_kb = p.stat().st_size / 1024.0
            dims = _get_image_dimensions_pure_python(p)
            feat_info = {"file": str(p), "size_kb": round(sz_kb, 1), "dimensions": dims}
            if sz_kb > 15360:
                results["valid"] = False
                results["errors"].append(f"Feature Graphic is too large ({sz_kb:.1f} KB, max: 15 MB).")
            if dims and (dims[0] != 1024 or dims[1] != 500):
                results["valid"] = False
                results["errors"].append(f"Feature Graphic dimensions must be exactly 1024x500 (found: {dims[0]}x{dims[1]}).")
            results["assets"]["feature_graphic"] = feat_info

    # Validate Screenshots
    if screenshots_dir:
        d = Path(screenshots_dir).resolve()
        if not d.is_dir():
            results["valid"] = False
            results["errors"].append(f"Screenshots directory not found at '{screenshots_dir}'.")
        else:
            img_files = sorted([f for f in d.iterdir() if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
            count = len(img_files)
            results["assets"]["screenshots_count"] = count
            if count < 2:
                results["valid"] = False
                results["errors"].append(f"At least 2 screenshots are required (found: {count}).")
            elif count > 8:
                results["warnings"].append(f"Google Play displays up to 8 screenshots per device type (found: {count}).")

    return results


def inspect_android_manifest_or_bundle(file_path: str) -> Dict[str, Any]:
    """Inspects an Android project, APK, AAB, or build.gradle to extract package, version, and SDK specifications."""
    p = Path(file_path).resolve()
    if not p.exists():
        return {"error": f"Path '{file_path}' does not exist.", "success": False}

    info: Dict[str, Any] = {
        "success": True,
        "file": str(p).replace("\\", "/"),
        "type": "unknown",
        "package_name": None,
        "version_code": None,
        "version_name": None,
        "min_sdk": None,
        "target_sdk": None,
    }

    # Inspect Gradle script (Kotlin DSL or Groovy)
    if p.is_file() and (p.name.startswith("build.gradle") or p.name.endswith(".gradle.kts")):
        info["type"] = "gradle_build_script"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            # applicationId takes priority over namespace
            app_id = re.search(r'applicationId\s*=?\s*["\']([^"\']+)["\']', text)
            if not app_id:
                app_id = re.search(r'namespace\s*=?\s*["\']([^"\']+)["\']', text)
            if app_id:
                info["package_name"] = app_id.group(1)
            # versionCode
            v_code = re.search(r'versionCode\s*=?\s*(\d+)', text)
            if v_code:
                info["version_code"] = int(v_code.group(1))
            # versionName
            v_name = re.search(r'versionName\s*=?\s*["\']([^"\']+)["\']', text)
            if v_name:
                info["version_name"] = v_name.group(1)
            # minSdk / targetSdk
            min_sdk = re.search(r'minSdk(?:Version)?\s*=?\s*(\d+)', text)
            if min_sdk:
                info["min_sdk"] = int(min_sdk.group(1))
            target_sdk = re.search(r'targetSdk(?:Version)?\s*=?\s*(\d+)', text)
            if target_sdk:
                info["target_sdk"] = int(target_sdk.group(1))
        except Exception as exc:
            return {"error": f"Failed to parse gradle file: {exc}", "success": False}


    # Inspect AndroidManifest.xml
    elif p.is_file() and p.name == "AndroidManifest.xml":
        info["type"] = "manifest_xml"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            pkg = re.search(r'package\s*=\s*["\']([^"\']+)["\']', text)
            if pkg:
                info["package_name"] = pkg.group(1)
            v_code = re.search(r'android:versionCode\s*=\s*["\'](\d+)["\']', text)
            if v_code:
                info["version_code"] = int(v_code.group(1))
            v_name = re.search(r'android:versionName\s*=\s*["\']([^"\']+)["\']', text)
            if v_name:
                info["version_name"] = v_name.group(1)
        except Exception as exc:
            return {"error": f"Failed to parse manifest: {exc}", "success": False}

    # Inspect ZIP / AAB structure
    elif p.is_file() and p.suffix.lower() in (".aab", ".apk", ".zip"):
        info["type"] = "android_archive"
        try:
            with zipfile.ZipFile(p, "r") as z:
                names = z.namelist()
                info["archive_files_count"] = len(names)
                info["has_base_manifest"] = any("AndroidManifest.xml" in n for n in names)
                info["has_dex"] = any(n.endswith(".dex") for n in names)
                info["has_resources"] = any("resources.pb" in n or "resources.arsc" in n for n in names)
        except Exception as exc:
            return {"error": f"Failed to inspect android archive: {exc}", "success": False}

    return info


def sync_play_console_metadata(
    asset_dir: str,
    package_name: str,
    edition_name: str,
    is_paid: bool = False,
    default_price_eur: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensures play-store-assets directory has complete package_name.txt, metadata.json and listing templates."""
    base_dir = Path(output_dir or asset_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    pkg_clean = str(package_name or "").strip()
    ed_clean = str(edition_name or "").strip()

    created_or_updated: List[str] = []

    # 1. package_name.txt
    pkg_file = base_dir / "package_name.txt"
    pkg_file.write_text(f"{pkg_clean}\n", encoding="utf-8")
    created_or_updated.append(str(pkg_file.name))

    # 2. metadata.json
    meta_file = base_dir / "metadata.json"
    meta_data = {
        "package_name": pkg_clean,
        "edition": ed_clean,
        "is_paid": bool(is_paid),
        "default_price_eur": str(default_price_eur or "0.00") if is_paid else "0.00",
        "default_language": "en-US",
        "category": "NEWS_AND_MAGAZINES",
        "content_rating": "EVERYONE",
    }
    meta_file.write_text(json.dumps(meta_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    created_or_updated.append(str(meta_file.name))

    return {
        "status": "success",
        "success": True,
        "asset_dir": str(base_dir).replace("\\", "/"),
        "package_name": pkg_clean,
        "edition": ed_clean,
        "files_synced": created_or_updated,
    }
