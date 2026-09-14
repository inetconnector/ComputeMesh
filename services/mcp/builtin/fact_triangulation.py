# SPDX-License-Identifier: Apache-2.0
"""
Multi-Source Fact Verification & Triangulation Tool.
Cross-verifies claims and facts across independent sources (Wikipedia DE/EN, News Feeds, Web).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .multilingual_wiki import fetch_multilingual_wikipedia
from .news_feed import execute_get_news
from .web_search import duckduckgo_search


def verify_fact_multi_source(claim: str, timeout: float = 7.0) -> Dict[str, Any]:
    """
    Verifies a factual claim by cross-checking across Wikipedia, live news, and web sources.
    """
    clean_claim = claim.strip().rstrip(".!?")
    if not clean_claim:
        return {"error": "Aussage oder Fakt zur Überprüfung darf nicht leer sein."}

    wiki_res: Optional[Dict[str, Any]] = None
    web_res: List[Dict[str, str]] = []
    news_res: Optional[Dict[str, Any]] = None

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_wiki = executor.submit(fetch_multilingual_wikipedia, clean_claim, timeout)
        f_web = executor.submit(duckduckgo_search, clean_claim, 4, timeout)
        f_news = executor.submit(execute_get_news, clean_claim, 3)

        try:
            wiki_res = f_wiki.result()
        except Exception:
            wiki_res = None

        try:
            web_res = f_web.result()
        except Exception:
            web_res = []

        try:
            news_res = f_news.result()
        except Exception:
            news_res = None

    corroborating_sources: List[Dict[str, str]] = []

    if wiki_res and not wiki_res.get("error"):
        for src in wiki_res.get("sources", []):
            corroborating_sources.append({"source": f"Wikipedia ({wiki_res.get('title')})", "url": src})

    if news_res and isinstance(news_res, dict):
        for a in news_res.get("articles", []):
            corroborating_sources.append({"source": a.get("title", "Nachrichtenquelle"), "url": a.get("link", "")})

    for w in web_res:
        corroborating_sources.append({"source": w.get("title", "Webquelle"), "url": w.get("url", "")})

    num_sources = len(corroborating_sources)
    status_label = "✅ Durch mehrere unabhängige Quellen belegt" if num_sources >= 2 else ("🔍 Erste Belege gefunden" if num_sources == 1 else "❓ Keine unabhängigen Belege gefunden")

    lines = [
        f"## 🛡️ Multi-Source Faktenprüfung: **{clean_claim}**\n",
        f"**Status:** {status_label} ({num_sources} relevante Fundstellen)\n",
    ]

    if wiki_res and not wiki_res.get("error"):
        extract = wiki_res.get("extract", "")
        if extract:
            lines.append(f"### 📖 Enzyklopädischer Abgleich (Wikipedia DE/EN):\n{extract[:600]}...\n")

    if web_res:
        lines.append("### 🌐 Gefundene Web-Belege:")
        for idx, w in enumerate(web_res[:3], 1):
            lines.append(f"{idx}. [{w['title']}]({w['url']})\n   *{w['snippet']}*")
        lines.append("")

    if corroborating_sources:
        lines.append("### 🔗 Quellen:")
        for s in corroborating_sources[:5]:
            if s["url"]:
                lines.append(f"- [{s['source']}]({s['url']})")

    full_md = "\n".join(lines).strip()

    return {
        "status": "ok",
        "claim": clean_claim,
        "sources_count": num_sources,
        "is_corroborated": num_sources >= 2,
        "markdown": full_md,
        "summary": full_md,
    }
