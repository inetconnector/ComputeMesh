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


def detect_locale_for_query(query: str) -> tuple[str, str, str, str]:
    """Returns (hl, gl, setlang, accept_lang) based on query language and location cues."""
    q = query.lower()
    # UK
    if any(w in q for w in ("london", "manchester", "edinburgh", "glasgow", "birmingham", "liverpool", "leeds", "bristol", "cardiff", "belfast")):
        return ("en", "GB", "en-GB", "en-GB,en;q=0.9,en-US;q=0.8")
    # French
    if any(w in q for w in ("paris", "lyon", "marseille", "bordeaux", "toulouse", "nice", "nantes", "strasbourg", "lille", "ce week-end", "billets", "concerts à", "événements")):
        return ("fr", "FR", "fr-FR", "fr-FR,fr;q=0.9,en;q=0.8")
    # Spanish
    if any(w in q for w in ("madrid", "barcelona", "valencia", "sevilla", "bilbao", "malaga", "zaragoza", "este fin de semana", "entradas", "conciertos en", "eventos en")):
        return ("es", "ES", "es-ES", "es-ES,es;q=0.9,en;q=0.8")
    # Italian
    if any(w in q for w in ("roma", "rome", "milano", "milan", "napoli", "torino", "bologna", "firenze", "venezia", "palermo", "questo fine settimana", "biglietti", "concerti a", "eventi a")):
        return ("it", "IT", "it-IT", "it-IT,it;q=0.9,en;q=0.8")
    # Dutch
    if any(w in q for w in ("amsterdam", "rotterdam", "den haag", "utrecht", "eindhoven", "groningen")):
        return ("nl", "NL", "nl-NL", "nl-NL,nl;q=0.9,en;q=0.8")
    # Polish
    if any(w in q for w in ("warsaw", "warschau", "warszawa", "krakow", "krakau", "kraków", "wroclaw", "gdansk", "poznan")):
        return ("pl", "PL", "pl-PL", "pl-PL,pl;q=0.9,en;q=0.8")
    # English / US / Worldwide
    if any(w in q for w in ("new york", "nyc", "los angeles", "chicago", "san francisco", "miami", "austin", "seattle", "dublin", "tokyo", "tokio", "sydney", "melbourne", "toronto", "vancouver", "tickets", "this weekend", "tonight", "live music in", "concerts in", "events in", "things to do")):
        return ("en", "US", "en-US", "en-US,en;q=0.9,de;q=0.8")
    # Default DACH
    return ("de", "DE", "de-DE", "de-DE,de;q=0.9,en;q=0.8")


def google_news_search(query: str, max_results: int = 5, timeout: float = 6.0) -> List[Dict[str, str]]:
    hl, gl, _, _ = detect_locale_for_query(query)
    encoded = urllib.parse.quote(query)
    ceid = f"{gl}:{hl}"
    url = f"https://news.google.com/rss/search?q={encoded}&hl={hl}&gl={gl}&ceid={ceid}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8"},
    )
    results: List[Dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
        root = ET.fromstring(content)
        for item in root.findall(".//item")[:max_results]:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            title = clean_html(title_el.text if title_el is not None and title_el.text else "")
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            desc = clean_html(desc_el.text if desc_el is not None and desc_el.text else "")
            if title and link:
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": desc,
                })
    except Exception:
        pass
    return results


def bing_rss_search(query: str, max_results: int = 5, timeout: float = 8.0) -> List[Dict[str, str]]:
    _, gl, setlang, accept_lang = detect_locale_for_query(query)
    encoded = urllib.parse.urlencode({"q": query, "format": "rss", "setlang": setlang, "cc": gl})
    url = f"https://www.bing.com/search?{encoded}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": accept_lang},
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


def yahoo_search(query: str, max_results: int = 5, timeout: float = 6.0) -> List[Dict[str, str]]:
    _, _, _, accept_lang = detect_locale_for_query(query)
    encoded = urllib.parse.urlencode({"p": query, "ei": "UTF-8"})
    url = f"https://search.yahoo.com/search?{encoded}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": accept_lang},
    )
    results: List[Dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
        for match in re.finditer(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h3>', content, re.IGNORECASE):
            raw_url, raw_title = match.groups()
            title = clean_html(raw_title)
            if title and raw_url and "yahoo.com" not in raw_url:
                results.append({"title": title, "url": raw_url, "snippet": ""})
            if len(results) >= max_results:
                break
    except Exception:
        pass
    return results


def categorize_cultural_item(title: str, snippet: str, url: str) -> tuple[str, str, int]:
    """Classifies a search result into a cultural archetype (badge, rubric, priority_score)."""
    text = f"{title} {snippet} {url}".lower()

    # 1. Autonome Zentren, Subkultur, Off-Spaces & DIY
    if any(k in text for k in (
        "klapperfeld", "autonom", "soziokultur", "freiraum", "off-space", "kulturzentrum", "kulturfabrik",
        "besetzt", "diy", "ajz", "az ", " az", "squat", "tiers-lieux", "friche", "centro social",
        "centri sociali", "grassroots", "keller z87", "cairo", "immerhin", "b-hof", "rote flora",
        "conne island", "druckluft", "e-werk", "schlachthof", "milchsackfabrik", "tanzhaus west", "tiefgrund"
    )):
        return ("🏛️ Subkultur & Autonome Freiräume", "subculture", 100)

    # 2. Live-Clubs, Jazzkeller, Underground-Bühnen & Kneipenkonzerte
    if any(k in text for k in (
        "jazzkeller", "kellerklub", "live-club", "live club", "kneipenkonzert", "open mic", "jazz club",
        "basement", "indie club", "café-concert", "sala de conciertos", "live-bühne", "live bühne", "akustik"
    )):
        return ("🎸 Live-Clubs & Underground-Bühnen", "live_clubs", 90)

    # 3. Dörfer, Kleinstädte & Käffer (Kommunale, dörfliche & historische Perlen)
    if any(k in text for k in (
        "bürgerhaus", "dorfgemeinschaftshaus", "gemeindezentrum", "kulturscheune", "scheune", "kleinkunstbühne",
        "schlosskonzert", "dorffest", "kirchweih", "kulturverein", "pfarrheim", "bürgersaal", "rathauskonzert",
        "dorfsaal", "village hall", "salle des fêtes", "casa de cultura", "pro loco", "fête de village"
    )):
        return ("🌾 Dorf-, Gemeinde- & Regionalkultur", "community_gems", 85)

    # 4. Lokale Kulturkalender & Stadtmagazine
    if any(k in text for k in (
        "stadtmagazin", "veranstaltungskalender", "ausgehtipps", "radar", "kulturkalender", "agenda",
        "termine", "guide", "what's on", "events calendar", "sorties"
    )):
        return ("📰 Lokale Kulturkalender & Stadtmagazine", "calendars", 80)

    # 5. Club, Party & Nightlife
    if any(k in text for k in ("party", "clubnacht", "dj set", "rave", "techno", "electronic", "disco", "disko")):
        return ("🪩 Club & Party", "party", 70)

    return ("🎟️ Veranstaltungen & Konzerte", "general", 60)


def deep_cultural_event_search(
    city: str,
    query_hint: str = "",
    max_results: int = 8,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    Executes a multi-vector deep cultural research strategy for any city, town, or village worldwide.

    Queries 4 distinct angles in parallel:
    1. Subkultur, DIY, Freiräume & Autonome/Soziokulturelle Zentren (z. B. Klapperfeld, Kulturfabrik, Off-Spaces)
    2. Indie Live-Clubs, Jazzkeller, Basement Stages & Kneipenkonzerte
    3. Dörfer, Kleinstädte & Käffer (Bürgerhäuser, Scheunen, Kleinkunstbühnen, Schlosskonzerte)
    4. Lokale Kulturkalender, Stadtmagazine & Radar / Guides
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    clean_city = (city or "").strip()
    if not clean_city:
        return {"city": "", "results": [], "categories": {}}

    hl, gl, _, _ = detect_locale_for_query(clean_city)

    # Formulate multi-angle research vectors tailored by language & region
    if hl == "fr":
        vectors = [
            (f"{clean_city} friche culturelle tiers-lieux squat concerts agenda programmation", "subculture"),
            (f"{clean_city} café-concert club de jazz musique live programmation ce week-end", "live_clubs"),
            (f"{clean_city} salle des fêtes maison de quartier fête de village événements", "community_gems"),
            (f"{clean_city} agenda culturel sorties événements programmation ce week-end", "calendars"),
        ]
    elif hl == "es":
        vectors = [
            (f"{clean_city} centro social okupado autogestionado conciertos agenda cultural", "subculture"),
            (f"{clean_city} sala de conciertos pequenos directos musica underground club", "live_clubs"),
            (f"{clean_city} casa de cultura fiestas populares asociacion cultural eventos", "community_gems"),
            (f"{clean_city} agenda cultural que hacer este fin de semana eventos conciertos", "calendars"),
        ]
    elif hl == "it":
        vectors = [
            (f"{clean_city} centro sociale occupato autogestito concerti live programmazione", "subculture"),
            (f"{clean_city} circolo arci musica dal vivo concerti club", "live_clubs"),
            (f"{clean_city} pro loco sagra festa patronale eventi concerti", "community_gems"),
            (f"{clean_city} cosa fare questo fine settimana eventi concerti guida", "calendars"),
        ]
    elif hl == "en":
        vectors = [
            (f"{clean_city} grassroots music venues underground DIY spaces gigs schedule", "subculture"),
            (f"{clean_city} basement indie gigs jazz club live sessions this weekend", "live_clubs"),
            (f"{clean_city} village hall community centre cultural association live music events", "community_gems"),
            (f"{clean_city} what's on alternative events guide gigs calendar this weekend", "calendars"),
        ]
    else:  # Default DACH / German
        vectors = [
            (f"{clean_city} Autonomes Zentrum Klapperfeld Kulturzentrum Off-Space DIY Konzerte Termine", "subculture"),
            (f"{clean_city} kleine Live Bühne Jazzkeller Club Konzerte Wochenende Termine", "live_clubs"),
            (f"{clean_city} Bürgerhaus Dorfgemeinschaftshaus Kulturscheune Kleinkunstbühne Schlosskonzert Termine", "community_gems"),
            (f"{clean_city} Stadtmagazin Veranstaltungskalender Ausgehtipps alternative Termine heute Wochenende", "calendars"),
        ]

    raw_candidates: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()

    with ThreadPoolExecutor(max_workers=len(vectors)) as executor:
        futures = {executor.submit(execute_web_search, q, max_results=4, timeout=timeout): family for q, family in vectors}
        for future in as_completed(futures):
            try:
                res = future.result()
                for item in res.get("results", []):
                    u = item.get("url", "")
                    t = item.get("title", "")
                    s = item.get("snippet", "")
                    if not u or not t:
                        continue
                    clean_u = u.split("?")[0].rstrip("/")
                    if clean_u in seen_urls:
                        continue
                    seen_urls.add(clean_u)

                    badge, rubric_key, score = categorize_cultural_item(t, s, u)
                    raw_candidates.append({
                        "title": t,
                        "url": u,
                        "snippet": s,
                        "badge": badge,
                        "rubric_key": rubric_key,
                        "score": score,
                    })
            except Exception:
                continue

    # Sort candidates by cultural archetype priority score
    raw_candidates.sort(key=lambda x: x["score"], reverse=True)
    selected = raw_candidates[:max_results]

    # Group by rubric
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in selected:
        badge = item["badge"]
        grouped.setdefault(badge, []).append(item)

    return {
        "city": clean_city,
        "total": len(selected),
        "results": selected,
        "rubrics": grouped,
    }


def execute_web_search(query: str, max_results: int = 5, timeout: float = 10.0) -> Dict[str, Any]:
    """
    Executes live web search using DuckDuckGo, Google News RSS, Bing RSS, or Yahoo Search.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "Suchanfrage darf nicht leer sein", "results": []}

    max_results = max(1, min(max_results, 10))

    # 1. Try DuckDuckGo first
    results = duckduckgo_search(query, max_results=max_results, timeout=timeout)
    source = "duckduckgo"

    # 2. Try Google News RSS search (with locale auto-tuning)
    if not results:
        results = google_news_search(query, max_results=max_results, timeout=timeout)
        if results:
            source = "google"

    # 3. Fallback to Bing RSS (with locale auto-tuning)
    if not results:
        results = bing_rss_search(query, max_results=max_results, timeout=timeout)
        if results:
            source = "bing"

    # 4. Fallback to Yahoo Search
    if not results:
        results = yahoo_search(query, max_results=max_results, timeout=timeout)
        if results:
            source = "yahoo"

    return {
        "query": query,
        "source": source,
        "total": len(results),
        "results": results,
    }


# Backwards-compatible alias
search_web = execute_web_search
