# SPDX-License-Identifier: Apache-2.0
"""Live public-URL content fetcher with fail-closed SSRF protection."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict

from .url_security import UnsafeTargetError, build_safe_public_opener, validate_public_url

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2"
MAX_RESPONSE_BYTES = 512 * 1024

STRIP_TAGS_RE = re.compile(r"(?is)<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>")
TAG_RE = re.compile(r"(?is)<[^>]+>")
SPACE_RE = re.compile(r"[ \t]+")
NEWLINE_RE = re.compile(r"\n\s*\n+")


def clean_web_page_html(raw_html: str, max_chars: int = 12000) -> str:
    if not raw_html:
        return ""
    text = STRIP_TAGS_RE.sub(" ", raw_html)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = "\n".join(lines)
    cleaned = NEWLINE_RE.sub("\n\n", cleaned).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + f"\n\n[... Inhalt nach {max_chars} Zeichen gekürzt ...]"
    return cleaned


def execute_web_fetch(url: str, max_chars: int = 12000, timeout: float = 12.0) -> Dict[str, Any]:
    target = str(url or "").strip()
    if not target:
        return {"error": "URL darf nicht leer sein", "url": ""}
    if len(target) > 4096:
        return {"error": "URL ist zu lang (maximal 4096 Zeichen).", "url": target[:256]}
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    try:
        output_limit = max(1, min(50000, int(max_chars)))
        request_timeout = float(timeout)
    except (TypeError, ValueError):
        return {"error": "max_chars und timeout müssen numerisch sein.", "url": target}
    if request_timeout <= 0 or request_timeout > 60:
        return {"error": "timeout muss zwischen 0 und 60 Sekunden liegen.", "url": target}

    try:
        validate_public_url(target)
    except UnsafeTargetError as exc:
        return {"error": str(exc), "url": target}

    req = urllib.request.Request(
        target,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        },
    )

    opener = build_safe_public_opener()
    try:
        with opener.open(req, timeout=request_timeout) as resp:
            final_url = resp.geturl() if hasattr(resp, "geturl") else target
            # Defense in depth: urllib's redirect handler validates every hop; also
            # validate the final URL before consuming the response body.
            validate_public_url(final_url)
            content_type = resp.headers.get("Content-Type", "")
            raw_bytes = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(raw_bytes) > MAX_RESPONSE_BYTES:
                return {
                    "error": f"Webseite überschreitet das Antwortlimit von {MAX_RESPONSE_BYTES} Bytes.",
                    "url": final_url,
                }
            raw = raw_bytes.decode("utf-8", errors="ignore")

        content = clean_web_page_html(raw, max_chars=output_limit)
        return {
            "url": final_url,
            "status": "ok",
            "content_type": content_type,
            "length": len(content),
            "content": content,
        }
    except UnsafeTargetError as exc:
        return {"error": str(exc), "url": target}
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code} beim Laden von '{target}'.", "url": target}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"error": f"Fehler beim Laden von '{target}': {reason}", "url": target}
