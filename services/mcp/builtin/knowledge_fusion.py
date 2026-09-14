# SPDX-License-Identifier: Apache-2.0
"""
Deep Multi-Source Knowledge Fusion & Autonomous Research Engine.
Harmonizes and triangulates German & English Wikipedia, Real-Time News Wires,
and Live Deep Web Search into a unified, high-fidelity knowledge package.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .context_resolver import resolve_contextual_query
from .multilingual_wiki import fetch_multilingual_wikipedia
from .news_feed import execute_get_news
from .web_search import duckduckgo_search


def cross_source_knowledge_search(
    query: str = "",
    topic: str = "",
    language: str = "de",
    timeout: float = 7.0,
    messages: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Executes deep cross-source research combining German & English Wikipedia,
    live news feeds (Tagesschau, Spiegel, Reuters RSS), and DuckDuckGo Web Search.
    """
    raw_query = (query or topic or "").strip()
    if not raw_query:
        return {"error": "Suchbegriff für die Wissensfusion darf nicht leer sein."}

    # Step 1: Resolve conversational deictic references if any
    resolved_query, resolved_entity, was_resolved = resolve_contextual_query(raw_query, messages)
    search_target = resolved_query if was_resolved else raw_query

    wiki_data: Optional[Dict[str, Any]] = None
    news_data: Optional[Dict[str, Any]] = None
    web_results: List[Dict[str, str]] = []

    # Step 2: Concurrent multi-source execution
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_wiki = executor.submit(fetch_multilingual_wikipedia, search_target, timeout)
        f_news = executor.submit(execute_get_news, search_target, 4)
        f_web = executor.submit(duckduckgo_search, search_target, 4, timeout)

        try:
            wiki_data = f_wiki.result()
        except Exception:
            wiki_data = None

        try:
            news_data = f_news.result()
        except Exception:
            news_data = None

        try:
            web_results = f_web.result()
        except Exception:
            web_results = []

    # Step 3: Format and triangulate unified knowledge blocks
    sections: List[str] = []
    citations: List[Dict[str, str]] = []

    header = f"## 🔍 Fundierte Multi-Source Recherche: **{resolved_entity or search_target}**"
    if was_resolved:
        header += f"\n*Kontext aufgelöst aus Unterhaltungsverlauf für: '{raw_query}'*"
    sections.append(header)

    # 1. Wikipedia Background (DE + EN)
    if wiki_data and not wiki_data.get("error"):
        wiki_text = str(wiki_data.get("extract") or wiki_data.get("summary") or "").strip()
        if wiki_text:
            sections.append(f"### 📖 Enzyklopädischer Hintergrund & Grundlagen\n{wiki_text}")
            for src in wiki_data.get("sources", []):
                citations.append({"title": f"Wikipedia ({wiki_data.get('title')})", "url": src})

    # 2. Real-Time News & Wire Updates
    if news_data and isinstance(news_data, dict):
        articles = news_data.get("articles") or []
        if articles:
            news_lines = ["### 📰 Aktuelle Nachrichten & Letzte Entwicklungen:"]
            for idx, a in enumerate(articles[:4], 1):
                t = a.get("title", "")
                link = a.get("link", "")
                src = a.get("source", "")
                pub = a.get("published", "")
                sum_txt = a.get("summary", "")
                meta_tag = f" *({src} • {pub})*" if src and pub else (f" *({src})*" if src else "")
                item_str = f"{idx}. [{t}]({link}){meta_tag}" if link else f"{idx}. **{t}**{meta_tag}"
                if sum_txt:
                    item_str += f"\n   *{sum_txt[:140]}...*"
                news_lines.append(item_str)
                if link and t:
                    citations.append({"title": t, "url": link})
            sections.append("\n".join(news_lines))

    # 3. Live Web Search & Specific Sources
    if web_results:
        web_lines = ["### 🌐 Web-Recherche & Vertiefende Quellen:"]
        for idx, w in enumerate(web_results[:4], 1):
            t = w.get("title", "")
            u = w.get("url", "")
            snip = w.get("snippet", "")
            web_lines.append(f"{idx}. [{t}]({u})\n   {snip}")
            if u and t:
                citations.append({"title": t, "url": u})
        sections.append("\n".join(web_lines))

    # Fallback if all external sources failed
    if len(sections) <= 1:
        return {
            "error": f"Zu '{search_target}' konnten weder auf Wikipedia, in Newsfeeds noch per Websuche Daten ermittelt werden.",
            "query": search_target,
            "resolved_from": raw_query if was_resolved else None,
        }

    # 4. Verified Citations
    if citations:
        unique_citations = []
        seen_urls = set()
        for c in citations:
            u = c.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                unique_citations.append(c)
        if unique_citations:
            cit_lines = ["### 🔗 Verifizierte Quellen & Nachweise:"]
            for c in unique_citations[:6]:
                cit_lines.append(f"- [{c['title']}]({c['url']})")
            sections.append("\n".join(cit_lines))

    full_markdown = "\n\n".join(sections).strip()

    return {
        "status": "success",
        "query": search_target,
        "resolved_entity": resolved_entity,
        "markdown": full_markdown,
        "summary": full_markdown,
        "has_wiki": bool(wiki_data and not wiki_data.get("error")),
        "has_news": bool(news_data and news_data.get("articles")),
        "has_web": bool(web_results),
        "citations_count": len(citations),
    }


# Backwards-compatible aliases
deep_research_topic = cross_source_knowledge_search
research_topic = cross_source_knowledge_search
