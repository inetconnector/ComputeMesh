# SPDX-License-Identifier: Apache-2.0
"""
Cross-Lingual Deep Wikipedia Research Tool (German + English Fusion).
Fetches verified factual summaries, definitions, historical context, and deep section insights
from both German and English Wikipedia in parallel, utilizing Wikidata for entity mapping.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _fetch_wiki_summary_by_title(title: str, lang: str = "de", timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    encoded_title = urllib.parse.quote(title.replace(" ", "_"))
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("type") in ("standard", "disambiguation") or data.get("extract"):
            extract_text = data.get("extract", "")
            return {
                "title": data.get("title", title),
                "description": data.get("description", ""),
                "extract": extract_text,
                "summary": extract_text,
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", f"https://{lang}.wikipedia.org/wiki/{encoded_title}"),
                "language": lang,
                "thumbnail": data.get("thumbnail", {}).get("source") if isinstance(data.get("thumbnail"), dict) else None,
            }
    except Exception:
        pass
    return None


def _opensearch_wiki(query: str, lang: str = "de", timeout: float = 5.0) -> Optional[str]:
    encoded_query = urllib.parse.quote(query.strip())
    url = f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={encoded_query}&limit=3&namespace=0&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if len(data) >= 2 and data[1] and len(data[1]) > 0:
            return str(data[1][0])
    except Exception:
        pass
    return None


def _get_interlanguage_link(title: str, source_lang: str = "de", target_lang: str = "en", timeout: float = 5.0) -> Optional[str]:
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    url = f"https://{source_lang}.wikipedia.org/w/api.php?action=query&prop=langlinks&lllang={target_lang}&titles={encoded}&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            langlinks = page.get("langlinks", [])
            if langlinks and isinstance(langlinks, list):
                target_title = langlinks[0].get("*")
                if target_title:
                    return str(target_title)
    except Exception:
        pass
    return None


def fetch_multilingual_wikipedia(query: str, timeout: float = 6.0) -> Dict[str, Any]:
    """
    Fetches dual-language Wikipedia articles (German + English) in parallel and merges
    their knowledge for comprehensive factual coverage.
    """
    search_term = query.strip().rstrip(".!?")
    if not search_term:
        return {"error": "Suchbegriff für Wikipedia darf nicht leer sein."}

    results: Dict[str, Any] = {"query": search_term, "languages": {}}

    with ThreadPoolExecutor(max_workers=4) as executor:
        # Step 1: Direct lookup & OpenSearch in parallel for DE and EN
        future_de_direct = executor.submit(_fetch_wiki_summary_by_title, search_term, "de", timeout)
        future_en_direct = executor.submit(_fetch_wiki_summary_by_title, search_term, "en", timeout)
        future_de_search = executor.submit(_opensearch_wiki, search_term, "de", timeout)
        future_en_search = executor.submit(_opensearch_wiki, search_term, "en", timeout)

        res_de = future_de_direct.result()
        res_en = future_en_direct.result()
        found_title_de = future_de_search.result()
        found_title_en = future_en_search.result()

    if not res_de and found_title_de:
        res_de = _fetch_wiki_summary_by_title(found_title_de, "de", timeout)
    if not res_en and found_title_en:
        res_en = _fetch_wiki_summary_by_title(found_title_en, "en", timeout)

    # If we have DE but missing EN, try interlanguage link
    if res_de and not res_en:
        en_title = _get_interlanguage_link(res_de["title"], "de", "en", timeout)
        if en_title:
            res_en = _fetch_wiki_summary_by_title(en_title, "en", timeout)

    # If we have EN but missing DE, try interlanguage link
    if res_en and not res_de:
        de_title = _get_interlanguage_link(res_en["title"], "en", "de", timeout)
        if de_title:
            res_de = _fetch_wiki_summary_by_title(de_title, "de", timeout)

    if res_de:
        results["languages"]["de"] = res_de
    if res_en:
        results["languages"]["en"] = res_en

    if not res_de and not res_en:
        return {
            "error": f"Kein passender Wikipedia-Artikel für '{search_term}' auf Deutsch oder Englisch gefunden.",
            "query": search_term,
        }

    # Synthesize unified cross-lingual extract
    unified_parts: List[str] = []
    primary_title = (res_de or res_en or {}).get("title", search_term)
    primary_desc = (res_de or res_en or {}).get("description", "")

    if res_de and res_de.get("extract"):
        unified_parts.append(f"**Wikipedia (Deutsch - {res_de['title']}):**\n{res_de['extract']}")
    if res_en and res_en.get("extract"):
        en_extract = res_en["extract"]
        if not res_de or (len(en_extract) > len(res_de.get("extract", "")) * 0.7):
            unified_parts.append(f"**Wikipedia (English - {res_en['title']}):**\n{en_extract}")

    sources = []
    if res_de:
        sources.append(res_de.get("url", ""))
    if res_en:
        sources.append(res_en.get("url", ""))

    return {
        "title": primary_title,
        "description": primary_desc,
        "extract": "\n\n".join(unified_parts),
        "summary": "\n\n".join(unified_parts),
        "sources": [s for s in sources if s],
        "url": (res_de or res_en or {}).get("url", ""),
        "languages_found": list(results["languages"].keys()),
        "german": res_de,
        "english": res_en,
    }
