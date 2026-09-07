# SPDX-License-Identifier: Apache-2.0
"""
Wikipedia & Encyclopedia Reference Tool.
Fetches verified factual summaries, definitions, scientific concepts, and biographies from Wikipedia.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _fetch_wiki_summary_by_title(title: str, lang: str = "de", timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    encoded_title = urllib.parse.quote(title.replace(" ", "_"))
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("type") == "standard" or data.get("extract"):
            return {
                "title": data.get("title"),
                "description": data.get("description", ""),
                "extract": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", f"https://{lang}.wikipedia.org/wiki/{encoded_title}"),
                "language": lang,
            }
    except Exception:
        pass
    return None


def _opensearch_wiki(query: str, lang: str = "de", timeout: float = 6.0) -> Optional[str]:
    encoded_query = urllib.parse.quote(query.strip())
    url = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={encoded_query}&limit=3&namespace=0&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # data format: [query, [titles], [descriptions], [urls]]
        if len(data) >= 2 and data[1] and len(data[1]) > 0:
            return data[1][0]
    except Exception:
        pass
    return None


def get_wikipedia_summary(
    query: str = "",
    title: str = "",
    topic: str = "",
    language: str = "de",
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    Fetches verified encyclopedia summaries, definitions, concepts, or biographies from Wikipedia.
    """
    search_term = (query or title or topic or "").strip()
    if not search_term:
        return {"error": "Suchbegriff oder Thema für Wikipedia darf nicht leer sein."}

    lang = (language or "de").strip().lower()
    if lang not in ("de", "en", "fr", "es", "it"):
        lang = "de"

    # 1. Direct title lookup in target language
    res = _fetch_wiki_summary_by_title(search_term, lang=lang, timeout=timeout / 2)
    if res:
        return res

    # 2. OpenSearch for best matching article title
    best_title = _opensearch_wiki(search_term, lang=lang, timeout=timeout / 2)
    if best_title:
        res = _fetch_wiki_summary_by_title(best_title, lang=lang, timeout=timeout / 2)
        if res:
            return res

    # 3. Fallback to English Wikipedia if German didn't find anything
    if lang != "en":
        res_en = _fetch_wiki_summary_by_title(search_term, lang="en", timeout=timeout / 2)
        if res_en:
            return res_en
        best_title_en = _opensearch_wiki(search_term, lang="en", timeout=timeout / 2)
        if best_title_en:
            res_en = _fetch_wiki_summary_by_title(best_title_en, lang="en", timeout=timeout / 2)
            if res_en:
                return res_en

    return {
        "error": f"Kein passender Wikipedia-Artikel für '{search_term}' gefunden.",
        "query": search_term,
    }


# Backwards-compatible alias
search_wikipedia = get_wikipedia_summary
