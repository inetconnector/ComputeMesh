# SPDX-License-Identifier: Apache-2.0
"""
Chronological Timeline & Event Sequence Builder.
Extracts and synthesizes dated occurrences and key milestones for any topic,
conflict, organization, or person from live news feeds and web records.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from .news_feed import execute_get_news
from .web_search import duckduckgo_search


def fetch_recent_timeline(topic: str = "", query: str = "", max_events: int = 6, timeout: float = 7.0) -> Dict[str, Any]:
    """
    Constructs a chronological event timeline with dates, summaries, and verified sources.
    """
    search_target = (topic or query or "").strip()
    if not search_target:
        return {"error": "Thema für die Zeitleiste darf nicht leer sein."}

    news_data: Optional[Dict[str, Any]] = None
    web_results: List[Dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_news = executor.submit(execute_get_news, search_target, max_events)
        f_web = executor.submit(duckduckgo_search, f"{search_target} Chronologie Verlauf letzte Ereignisse", max_events, timeout)

        try:
            news_data = f_news.result()
        except Exception:
            news_data = None

        try:
            web_results = f_web.result()
        except Exception:
            web_results = []

    events: List[Dict[str, str]] = []
    seen_titles: set[str] = set()

    # Process news articles with dates
    if news_data and isinstance(news_data, dict):
        articles = news_data.get("articles") or []
        for a in articles:
            title = a.get("title", "").strip()
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())
            events.append({
                "date": a.get("published", "Kürzlich"),
                "title": title,
                "summary": a.get("summary", ""),
                "source": a.get("source", "Nachrichten"),
                "link": a.get("link", ""),
            })

    # Add web search records if needed
    for w in web_results:
        t = w.get("title", "").strip()
        if not t or t.lower() in seen_titles or len(events) >= max_events:
            continue
        seen_titles.add(t.lower())
        events.append({
            "date": "Aktuelle Recherche",
            "title": t,
            "summary": w.get("snippet", ""),
            "source": "Websuche",
            "link": w.get("url", ""),
        })

    if not events:
        return {
            "error": f"Für '{search_target}' konnten keine aktuellen Ereignisse oder Zeitleisten-Einträge ermittelt werden.",
            "topic": search_target,
        }

    # Format into markdown timeline
    lines = [f"## ⏱️ Chronologische Zeitleiste: **{search_target}**\n"]
    lines.append("*Strukturierte Übersicht der jüngsten Ereignisse und Entwicklungen:*\n")

    for idx, ev in enumerate(events[:max_events], 1):
        dt = ev["date"]
        t = ev["title"]
        snip = ev["summary"]
        src = ev["source"]
        link = ev["link"]
        source_tag = f" — [{src}]({link})" if link else f" — *{src}*"

        lines.append(f"### {idx}. 📅 `{dt}`: **{t}**{source_tag}")
        if snip:
            lines.append(f"> {snip.strip()}\n")
        else:
            lines.append("")

    full_md = "\n".join(lines).strip()

    return {
        "status": "ok",
        "topic": search_target,
        "total_events": len(events),
        "events": events[:max_events],
        "markdown": full_md,
        "summary": full_md,
    }
