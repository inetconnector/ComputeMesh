# SPDX-License-Identifier: Apache-2.0
"""Universal HTTP REST API Client and Webhook Tool for ComputeMesh."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger("computemesh.mcp.http_api_client")
DEFAULT_USER_AGENT = "ComputeMesh-REST-Client/1.2"

PRIVATE_HOST_PATTERNS = [
    r"^localhost$",
    r"^127\.\d+\.\d+\.\d+$",
    r"^::1$",
    r"^0\.0\.0\.0$",
    r"^10\.\d+\.\d+\.\d+$",
    r"^192\.168\.\d+\.\d+$",
    r"^172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+$",
    r"^169\.254\.\d+\.\d+$",
]


def execute_http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[str] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 15.0,
) -> Dict[str, Any]:
    """Executes arbitrary HTTP REST API requests (GET, POST, PUT, DELETE, PATCH)."""
    clean_url = str(url or "").strip()
    if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        return {"error": "Ungültige URL: Muss mit http:// oder https:// beginnen.", "success": False}

    # SSRF / Private IP protection
    try:
        parsed_url = urllib.parse.urlparse(clean_url)
        hostname = (parsed_url.hostname or "").lower()
        for pat in PRIVATE_HOST_PATTERNS:
            if re.match(pat, hostname):
                return {
                    "error": "Sicherheitsrichtlinie: Lokale und private IP-Adressen sind aus Sicherheitsgründen blockiert.",
                    "success": False,
                    "status_code": 403,
                }
    except Exception:
        pass

    if params:
        clean_params = {k: v for k, v in params.items() if v is not None}
        if clean_params:
            sep = "&" if "?" in clean_url else "?"
            clean_url += sep + urllib.parse.urlencode(clean_params)

    req_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json, text/plain, */*"}
    if headers and isinstance(headers, dict):
        req_headers.update(headers)

    req_data = None
    if json_body is not None:
        req_headers["Content-Type"] = "application/json; charset=utf-8"
        req_data = json.dumps(json_body).encode("utf-8")
    elif body is not None and method.upper() in ("POST", "PUT", "PATCH"):
        if not any(k.lower() == "content-type" for k in req_headers):
            req_headers["Content-Type"] = "application/json; charset=utf-8" if (body.strip().startswith("{") or body.strip().startswith("[")) else "text/plain; charset=utf-8"
        req_data = body.encode("utf-8")

    req = urllib.request.Request(clean_url, data=req_data, headers=req_headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            status_code = getattr(resp, "status", getattr(resp, "code", 200))
            if callable(status_code):
                status_code = status_code()
            raw = resp.read(512 * 1024)  # 512 KB limit
            resp_headers = dict(resp.headers.items()) if hasattr(resp, "headers") and resp.headers else {}

            try:
                parsed_json = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                parsed_json = None

            text_body = raw.decode("utf-8", errors="replace")

            return {
                "success": 200 <= status_code < 300,
                "url": clean_url,
                "method": method.upper(),
                "status_code": status_code,
                "reason": getattr(resp, "reason", "OK"),
                "headers": {k: v for k, v in list(resp_headers.items())[:10]},
                "data": parsed_json if parsed_json is not None else text_body,
                "json_data": parsed_json,
                "body_preview": text_body[:2000],
            }

    except urllib.error.HTTPError as exc:
        raw_err = exc.read(64 * 1024).decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        return {
            "success": False,
            "url": clean_url,
            "method": method.upper(),
            "status_code": exc.code,
            "reason": exc.reason,
            "error": f"HTTP {exc.code}: {exc.reason}",
            "response_body": raw_err[:2000],
            "body_preview": raw_err[:2000],
        }
    except Exception as exc:
        return {"success": False, "url": clean_url, "error": f"Netzwerkfehler: {exc}"}
