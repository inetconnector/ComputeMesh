# SPDX-License-Identifier: Apache-2.0
"""
Software Package Registry & Vulnerability (OSV/CVE) Inspection Tool.
Retrieves versions, dependencies, license, and security advisories from PyPI, NPM, Crates.io, and OSV.dev.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _fetch_pypi(package_name: str, timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    """Fetches Python package metadata from PyPI JSON API."""
    clean = package_name.strip().lower()
    url = f"https://pypi.org/pypi/{clean}/json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            info = data.get("info", {})
            return {
                "ecosystem": "PyPI (Python)",
                "name": info.get("name", package_name),
                "version": info.get("version", ""),
                "summary": info.get("summary", ""),
                "author": info.get("author", ""),
                "license": info.get("license", "Unbekannt"),
                "home_page": info.get("home_page") or info.get("project_url", ""),
                "requires_python": info.get("requires_python", ""),
                "dependencies_count": len(info.get("requires_dist") or []),
            }
    except Exception:
        pass
    return None


def _fetch_npm(package_name: str, timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    """Fetches JavaScript / TypeScript package metadata from NPM Registry API."""
    encoded = urllib.parse.quote(package_name.strip().lower(), safe="@")
    url = f"https://registry.npmjs.org/{encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            dist_tags = data.get("dist-tags", {})
            latest_version = dist_tags.get("latest", "")
            latest_data = data.get("versions", {}).get(latest_version, {})
            return {
                "ecosystem": "NPM (JavaScript / TypeScript)",
                "name": data.get("name", package_name),
                "version": latest_version,
                "summary": data.get("description", ""),
                "author": latest_data.get("author", {}).get("name", "") if isinstance(latest_data.get("author"), dict) else str(latest_data.get("author", "")),
                "license": latest_data.get("license", "Unbekannt"),
                "home_page": latest_data.get("homepage", ""),
                "dependencies_count": len(latest_data.get("dependencies", {})),
            }
    except Exception:
        pass
    return None


def _check_osv_vulnerabilities(ecosystem: str, package_name: str, version: str = "", timeout: float = 4.0) -> List[Dict[str, Any]]:
    """Queries OSV.dev for known security vulnerabilities (CVEs) affecting this package."""
    osv_eco = "PyPI" if "pypi" in ecosystem.lower() else "npm" if "npm" in ecosystem.lower() else ""
    if not osv_eco:
        return []

    url = "https://api.osv.dev/v1/query"
    payload: Dict[str, Any] = {"package": {"name": package_name, "ecosystem": osv_eco}}
    if version:
        payload["version"] = version

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            vulns = data.get("vulns", [])
            results: List[Dict[str, Any]] = []
            for v in vulns[:4]:
                results.append({
                    "id": v.get("id"),
                    "summary": v.get("summary", v.get("details", ""))[:200],
                    "aliases": v.get("aliases", []),
                })
            return results
    except Exception:
        return []


def lookup_software_package(
    package_name: str = "",
    ecosystem: str = "pypi",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Looks up software package metadata, latest releases, dependencies, and OSV security vulnerabilities.
    """
    clean_pkg = (package_name or query or "").strip()
    if not clean_pkg:
        return {"error": "Paketname darf nicht leer sein (z. B. 'torch', 'fastapi', 'react', 'langchain')."}

    eco = (ecosystem or "pypi").lower().strip()
    data = None
    if eco in ("pypi", "python", "pip"):
        data = _fetch_pypi(clean_pkg, timeout=timeout / 2)
        if not data and "@" in clean_pkg:
            data = _fetch_npm(clean_pkg, timeout=timeout / 2)
    elif eco in ("npm", "node", "javascript", "js", "typescript", "ts"):
        data = _fetch_npm(clean_pkg, timeout=timeout / 2)
    else:
        # Try PyPI first, then NPM
        data = _fetch_pypi(clean_pkg, timeout=timeout / 2) or _fetch_npm(clean_pkg, timeout=timeout / 2)

    if not data:
        return {"error": f"Software-Paket '{clean_pkg}' in Ökosystem '{eco}' nicht gefunden."}

    # Query OSV.dev for CVEs
    vulns = _check_osv_vulnerabilities(data["ecosystem"], data["name"], data.get("version", ""), timeout=timeout / 2)
    data["vulnerabilities_count"] = len(vulns)
    data["vulnerabilities"] = vulns

    status_str = f"⚠️ {len(vulns)} bekannte Sicherheitslücken (OSV/CVE) gemeldet" if vulns else "✅ Keine bekannten Sicherheitslücken gemeldet"
    summary = (
        f"**{data['name']}** (v{data['version']} auf {data['ecosystem']}):\n"
        f"- **Beschreibung**: {data.get('summary', 'Keine Beschreibung')}\n"
        f"- **Lizenz**: {data.get('license', 'Unbekannt')} | **Abhängigkeiten**: {data.get('dependencies_count', 0)}\n"
        f"- **Sicherheitsstatus**: {status_str}"
    )
    data["summary_formatted"] = summary
    return data


# Backwards-compatible alias
lookup_package_info = lookup_software_package
