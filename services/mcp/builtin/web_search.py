# SPDX-License-Identifier: Apache-2.0
"""
Live Web Search Tool (DuckDuckGo HTML + Bing RSS Fallback).
Ported and adapted from LocalCode/src/web_tools.go.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

TAG_RE = re.compile(r"(?is)<[^>]+>")
SPACE_RE = re.compile(r"\s+")
DDG_RESULT_RE = re.compile(
    r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>'
)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 ComputeMesh/1.2"


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = TAG_RE.sub(" ", raw_html)
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def duckduckgo_search(query: str, max_results: int = 5, timeout: float = 8.0) -> List[Dict[str, str]]:
    encoded = urllib.parse.urlencode({"q": query, "b": ""})
    url = f"https://html.duckduckgo.com/html/?{encoded}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )

    results: List[Dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        for match in DDG_RESULT_RE.finditer(content):
            raw_url, raw_title, raw_snippet = match.groups()
            
            # DuckDuckGo wraps target url in uddg parameter
            target_url = raw_url
            if "uddg=" in raw_url:
                parsed = urllib.parse.urlparse(raw_url)
                qs = urllib.parse.parse_qs(parsed.query)
                if "uddg" in qs and qs["uddg"]:
                    target_url = qs["uddg"][0]

            title = clean_html(raw_title)
            snippet = clean_html(raw_snippet)

            if title and snippet:
                results.append({
                    "title": title,
                    "url": target_url,
                    "snippet": snippet,
                })
            if len(results) >= max_results:
                break
    except Exception:
        pass

    return results


def bing_rss_search(query: str, max_results: int = 5, timeout: float = 8.0) -> List[Dict[str, str]]:
    encoded = urllib.parse.urlencode({"q": query, "format": "rss"})
    url = f"https://www.bing.com/search?{encoded}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    results: List[Dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        root = ET.fromstring(content)
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")

                title = clean_html(title_el.text) if title_el is not None and title_el.text else ""
                link = link_el.text if link_el is not None and link_el.text else ""
                snippet = clean_html(desc_el.text) if desc_el is not None and desc_el.text else ""

                if title and link:
                    results.append({
                        "title": title,
                        "url": link,
                        "snippet": snippet,
                    })
                if len(results) >= max_results:
                    break
    except Exception:
        pass

    return results


def execute_web_search(query: str, max_results: int = 5, timeout: float = 10.0) -> Dict[str, Any]:
    """
    Executes live web search using DuckDuckGo with fallback to Bing RSS.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "Suchanfrage darf nicht leer sein", "results": []}

    max_results = max(1, min(max_results, 10))

    # Try DuckDuckGo first
    results = duckduckgo_search(query, max_results=max_results, timeout=timeout)
    source = "duckduckgo"

    # Fallback to Bing RSS if DuckDuckGo returned nothing
    if not results:
        results = bing_rss_search(query, max_results=max_results, timeout=timeout)
        source = "bing"

    return {
        "query": query,
        "source": source,
        "total": len(results),
        "results": results,
    }
