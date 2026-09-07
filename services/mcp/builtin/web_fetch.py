# SPDX-License-Identifier: Apache-2.0
"""
Live URL Web Content Fetcher & Text Extractor.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any, Dict

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2"

STRIP_TAGS_RE = re.compile(r"(?is)<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>")
TAG_RE = re.compile(r"(?is)<[^>]+>")
SPACE_RE = re.compile(r"[ \t]+")
NEWLINE_RE = re.compile(r"\n\s*\n+")


def clean_web_page_html(raw_html: str, max_chars: int = 12000) -> str:
    if not raw_html:
        return ""
    # Strip scripts, styles, headers, footers
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
    url = (url or "").strip()
    if not url:
        return {"error": "URL darf nicht leer sein", "url": ""}

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    parsed = urllib.parse.urlparse(url)
    if parsed.hostname in ("localhost", "127.0.0.1", "::1", "169.254.169.254"):
        return {"error": "Zugriff auf interne Loopback-Adressen verweigert.", "url": url}

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(1024 * 512).decode("utf-8", errors="ignore")  # Max 512KB

        content = clean_web_page_html(raw, max_chars=max_chars)
        return {
            "url": url,
            "status": "ok",
            "content_type": content_type,
            "length": len(content),
            "content": content,
        }
    except Exception as e:
        return {
            "error": f"Fehler beim Laden von '{url}': {str(e)}",
            "url": url,
        }
