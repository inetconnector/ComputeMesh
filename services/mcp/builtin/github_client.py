# SPDX-License-Identifier: Apache-2.0
"""Hardened GitHub REST API v3 Client for ComputeMesh Agentic Coding."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger("computemesh.mcp.github_client")

GITHUB_API_BASE = "https://api.github.com"
USER_AGENT = "ComputeMesh-Agent/1.2 (+https://computemesh.inetconnector.com)"


def get_github_token() -> Optional[str]:
    """Retrieves GitHub token from environment variables if configured."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def execute_github_request(
    endpoint: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    accept_header: str = "application/vnd.github.v3+json",
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """Executes an authenticated or public HTTPS request against the GitHub REST API."""
    clean_endpoint = "/" + endpoint.strip().lstrip("/")
    url = f"{GITHUB_API_BASE}{clean_endpoint}"

    if params:
        clean_params = {k: v for k, v in params.items() if v is not None}
        if clean_params:
            url += "?" + urllib.parse.urlencode(clean_params)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept_header,
        "X-GitHub-Api-Version": "2022-11-28",
    }

    token = get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"

    data_bytes = None
    if json_body is not None and method.upper() in ("POST", "PATCH", "PUT"):
        headers["Content-Type"] = "application/json; charset=utf-8"
        data_bytes = json.dumps(json_body).encode("utf-8")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = getattr(resp, "status", 200)
            raw_data = resp.read()
            rate_limit_rem = resp.headers.get("X-RateLimit-Remaining")

            if "diff" in accept_header or "raw" in accept_header:
                text_content = raw_data.decode("utf-8", errors="replace")
                return {
                    "success": True,
                    "status_code": status_code,
                    "data": text_content,
                    "rate_limit_remaining": int(rate_limit_rem) if rate_limit_rem else None,
                }

            try:
                parsed_json = json.loads(raw_data.decode("utf-8", errors="replace"))
            except Exception:
                parsed_json = raw_data.decode("utf-8", errors="replace")

            return {
                "success": True,
                "status_code": status_code,
                "data": parsed_json,
                "rate_limit_remaining": int(rate_limit_rem) if rate_limit_rem else None,
            }

    except urllib.error.HTTPError as exc:
        err_msg = f"HTTP {exc.code}: {exc.reason}"
        try:
            err_body = json.loads(exc.read().decode("utf-8", errors="replace"))
            if isinstance(err_body, dict) and "message" in err_body:
                err_msg = f"GitHub API Fehler ({exc.code}): {err_body['message']}"
        except Exception:
            pass
        return {
            "success": False,
            "status_code": exc.code,
            "error": err_msg,
            "rate_limit_remaining": int(exc.headers.get("X-RateLimit-Remaining", 0)) if exc.headers else 0,
        }
    except Exception as exc:
        return {"success": False, "status_code": 500, "error": f"Verbindungsfehler zu GitHub: {exc}"}
