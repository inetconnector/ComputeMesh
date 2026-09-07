# SPDX-License-Identifier: Apache-2.0
"""
Live News Feed & Current Events Tool.
Fetches real-time breaking news across Technology, Business, Crypto, Politics, and Global Affairs.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2"

TAG_RE = re.compile(r"(?is)<[^>]+>")
SPACE_RE = re.compile(r"\s+")

# Curated High-Reliability RSS News Feeds
NEWS_FEEDS = {
    "tech": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=de&gl=DE&ceid=DE:de",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=de&gl=DE&ceid=DE:de",
    "finance": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=de&gl=DE&ceid=DE:de",
    "general": "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de",
    "germany": "https://www.tagesschau.de/xml/rss2/",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=de&gl=DE&ceid=DE:de",
    "crypto": "https://news.google.com/rss/search?q=bitcoin+crypto+ethereum&hl=de&gl=DE&ceid=DE:de",
}


def clean_text(s: str) -> str:
    if not s:
        return ""
    text = TAG_RE.sub(" ", s)
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def fetch_rss_news(rss_url: str, max_items: int = 5, timeout: float = 8.0) -> List[Dict[str, str]]:
    req = urllib.request.Request(
        rss_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8"},
    )
    items: List[Dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        root = ET.fromstring(content)
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                desc_el = item.find("description")
                source_el = item.find("source")

                title = clean_text(title_el.text) if title_el is not None and title_el.text else ""
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
                desc = clean_text(desc_el.text) if desc_el is not None and desc_el.text else ""
                source = source_el.text.strip() if source_el is not None and source_el.text else ""

                if title:
                    items.append({
                        "title": title,
                        "source": source,
                        "published": pub_date,
                        "summary": desc,
                        "link": link,
                    })
                if len(items) >= max_items:
                    break
    except Exception:
        pass
    return items


def execute_get_news(topic: str = "general", max_results: int = 5, timeout: float = 10.0) -> Dict[str, Any]:
    """
    Fetches real-time news articles by topic or custom search term.
    """
    clean_topic = (topic or "general").strip().lower()
    max_results = max(1, min(max_results, 10))

    if clean_topic in NEWS_FEEDS:
        feed_url = NEWS_FEEDS[clean_topic]
        results = fetch_rss_news(feed_url, max_items=max_results, timeout=timeout)
    else:
        # Custom topic search query via Google News RSS
        encoded_query = urllib.parse.quote(clean_topic)
        feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=de&gl=DE&ceid=DE:de"
        results = fetch_rss_news(feed_url, max_items=max_results, timeout=timeout)

    return {
        "topic": clean_topic,
        "total": len(results),
        "articles": results,
    }
