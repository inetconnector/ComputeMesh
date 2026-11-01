# SPDX-License-Identifier: Apache-2.0
"""
Product search-snippet price extraction with explicit uncertainty.
Never represent simulated offers or unverified snippets as live merchant quotes.
"""

from __future__ import annotations

import html
import math
import re
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 ComputeMesh/1.2"

# Known major merchant domain mappings
MERCHANT_DOMAINS = {
    "amazon": "Amazon.de",
    "mindfactory": "Mindfactory.de",
    "mediamarkt": "MediaMarkt.de",
    "saturn": "Saturn.de",
    "cyberport": "Cyberport.de",
    "otto": "Otto.de",
    "alternate": "Alternate.de",
    "notebooksbilliger": "Notebooksbilliger.de",
    "nbb": "Notebooksbilliger.de",
    "galaxus": "Galaxus.de",
    "caseking": "Caseking.de",
    "conrad": "Conrad Electronic",
    "expert": "Expert.de",
    "euronics": "Euronics.de",
    "coolblue": "Coolblue.de",
    "reichelt": "Reichelt Elektronik",
    "ebay": "eBay.de",
    "idealo": "Idealo Partner",
    "geizhals": "Geizhals Partner",
    "apple": "Apple Store (UVP)",
    "samsung": "Samsung Online Shop",
    "sony": "Sony Store",
    "dyson": "Dyson Store",
}

# Pre-compiled regexes for price extraction
PRICE_REGEXES = [
    # Format: 1.199,00 € or 1199,99 EUR or 1.199 €
    re.compile(r'(?<!\d)(?:ab\s+|preis\s*:\s*|nur\s*|für\s*)?(\d{1,5}(?:\.\d{3})*,\d{2})\s*(?:€|eur|euro)', re.IGNORECASE),
    # Format: 1,199.00 $ or $1,199.00 or $1199
    re.compile(r'(?:\$|usd)\s*(\d{1,3}(?:,\d{3})*\.\d{2})', re.IGNORECASE),
    re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2})\s*(?:\$|usd)', re.IGNORECASE),
    # Format: 1199 € or 1.199 € (without decimals)
    re.compile(r'(\d{1,3}(?:\.\d{3})+|\d{2,5})\s*(?:€|eur|euro)', re.IGNORECASE),
    # Format: € 1199,00
    re.compile(r'(?:€|eur)\s*(\d{1,5}(?:\.\d{3})*(?:,\d{2})?)(?!\d)', re.IGNORECASE),
]


def clean_html_text(raw_html: str) -> str:
    """Removes HTML tags and decodes entities."""
    if not raw_html:
        return ""
    text = re.sub(r"(?is)<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_numeric_price(price_str: str) -> float | None:
    """Parses arbitrary European/US price strings into float."""
    if not price_str:
        return 0.0
    cleaned = str(price_str).strip().replace("€", "").replace("$", "").replace("EUR", "").replace("USD", "").replace(".-", "").replace("ab", "").replace("nur", "").strip()
    if not cleaned:
        return 0.0

    # Handle dual separators: 1.249,99 vs 1,249.99
    if "," in cleaned and "." in cleaned:
        last_dot = cleaned.rfind(".")
        last_comma = cleaned.rfind(",")
        if last_comma > last_dot:
            # European: 1.249,99 -> 1249.99
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US: 1,249.99 -> 1249.99
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts[-1]) == 3 and len(parts) > 1:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts[-1]) == 3 and len(parts) > 1:
            cleaned = cleaned.replace(".", "")

    try:
        val = float(cleaned)
        return round(val, 2) if math.isfinite(val) and val >= 0 else 0.0
    except ValueError:
        return 0.0


def _safe_offer_host(url: str) -> str | None:
    """Only permit direct HTTPS, public-looking DNS URLs without embedded credentials."""
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return None
    if (parsed.scheme != "https" or parsed.username is not None
            or parsed.password is not None or not host or "\\" in url
            or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host)
            or host.endswith((".localhost", ".local", ".internal", ".invalid", ".test"))
            or host in ("localhost", "127.0.0.1", "0.0.0.0")):
        return None
    # Prevent raw IPs, private/public alike, from being treated as a merchant website.
    if all(part.isdigit() for part in host.split(".")):
        return None
    try:
        if parsed.port is not None and parsed.port != 443:
            return None
    except ValueError:
        return None
    return host


# Exact registered domains, not substring matching: "amazon.de.evil.com" is not Amazon.
_MERCHANT_HOSTS = {
    "amazon.de": "Amazon.de",
    "mindfactory.de": "Mindfactory.de",
    "mediamarkt.de": "MediaMarkt.de",
    "saturn.de": "Saturn.de",
    "cyberport.de": "Cyberport.de",
    "otto.de": "Otto.de",
    "alternate.de": "Alternate.de",
    "notebooksbilliger.de": "Notebooksbilliger.de",
    "galaxus.de": "Galaxus.de",
    "caseking.de": "Caseking.de",
    "conrad.de": "Conrad Electronic",
    "expert.de": "Expert.de",
    "euronics.de": "Euronics.de",
    "coolblue.de": "Coolblue.de",
    "reichelt.de": "Reichelt Elektronik",
    "ebay.de": "eBay.de",
    "idealo.de": "Idealo Partner",
    "geizhals.de": "Geizhals Partner",
    "apple.com": "Apple Store",
    "samsung.com": "Samsung Online Shop",
    "sony.de": "Sony Store",
    "dyson.de": "Dyson Store",
}


def extract_merchant_name(url: str, title: str = "", snippet: str = "") -> str:
    """Identify a shop only from the validated destination host, not search text."""
    host = _safe_offer_host(url)
    if host is None:
        return "Online-Händler"
    for suffix, merchant in _MERCHANT_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return merchant
    return host

def fetch_live_shopping_offers(query: str, timeout: float = 6.0) -> list[dict[str, Any]]:
    """
    Fetches real-time shopping offers from DuckDuckGo HTML and e-commerce shopping engines.
    """
    search_q = f"{query} preisvergleich kaufen online shop"
    encoded = urllib.parse.urlencode({"q": search_q, "b": ""})
    url = f"https://html.duckduckgo.com/html/?{encoded}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8",
        },
    )

    offers: list[dict[str, Any]] = []
    seen_merchants = set()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Bound untrusted HTML size; avoid memory amplification on oversized responses.
            content_bytes = resp.read(2_000_001)
            if len(content_bytes) > 2_000_000:
                return []
            content = content_bytes.decode("utf-8", errors="ignore")

        item_re = re.compile(
            r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>'
        )

        for match in item_re.finditer(content):
            raw_url, raw_title, raw_snippet = match.groups()
            target_url = raw_url
            if "uddg=" in raw_url:
                parsed = urllib.parse.urlparse(raw_url)
                qs = urllib.parse.parse_qs(parsed.query)
                if "uddg" in qs and qs["uddg"]:
                    target_url = qs["uddg"][0]

            # A search engine can return a redirect to a non-web or local URI.
            # Never emit a merchant link to an unvalidated destination.
            if _safe_offer_host(target_url) is None:
                continue

            title = clean_html_text(raw_title)
            snippet = clean_html_text(raw_snippet)
            combined_text = f"{title} {snippet}"

            # Extract price
            found_price = None
            for p_re in (PRICE_REGEXES[0], *PRICE_REGEXES[3:]):
                # USD snippets cannot be compared as EUR without a verified exchange rate.
                m_p = p_re.search(combined_text)
                if m_p:
                    p_str = m_p.group(1)
                    parsed_p = parse_numeric_price(p_str)
                    if parsed_p and 5.0 <= parsed_p <= 25000.0:
                        found_price = parsed_p
                        break

            if found_price is not None:
                merchant = extract_merchant_name(target_url, title, snippet)
                if merchant in seen_merchants:
                    continue
                seen_merchants.add(merchant)

                # Search snippets are not verified merchant stock or shipping quotes.
                shipping_str = (
                    "0,00 € (laut Suchtreffer)"
                    if "kostenlos" in combined_text.lower() or "versandkostenfrei" in combined_text.lower()
                    else "Unbekannt"
                )
                avail_str = "Nicht verifiziert"

                offers.append({
                    "merchant": merchant,
                    "title": title[:70],
                    "price": found_price,
                    "currency": "EUR",
                    "shipping": shipping_str,
                    "availability": avail_str,
                    "url": target_url,
                    "source": "search_snippet_unverified",
                    "verified": False,
                })

            if len(offers) >= 8:
                break
    except Exception:
        pass

    return offers


def get_curated_benchmark_offers(query: str) -> list[dict[str, Any]]:
    """Retired compatibility endpoint: synthetic offers are not market quotes.

    The former hard-coded merchant names, in-stock statements and prices were
    indistinguishable from real offers. Preserve the symbol for old callers,
    but return no invented pricing or availability data.
    """
    return []


def search_product_prices(
    query: str,
    category: str | None = None,
    max_offers: int = 6,
    country: str = "DE",
    country_code: str | None = None,
    sort_by: str = "price_asc",
    timeout: float = 6.0,
) -> dict[str, Any]:
    """
    Extracts unverified EUR price hints from German-language web search snippets.

    Not a verified live merchant-price API. Never claim stock, shipping, best
    total price, savings, or seller identity without independent verification.

    Args:
        query: Name or keywords of the product (e.g. 'iPhone 16 Pro 256GB', 'RTX 4090').
        category: Optional product category (e.g. 'Smartphones', 'Hardware', 'Audio').
        max_offers: Number of top merchant offers to return (default: 6, max: 10).
        country: Target country code for shopping (default: 'DE').
        country_code: Alias for country.
        sort_by: Sorting criterion ('price_asc', 'rating', 'relevance').
        timeout: Network timeout in seconds.

    Returns:
        Structured price comparison data with best price, average price, savings, and merchant offers.
    """
    effective_country = country_code or country or "DE"
    if not isinstance(effective_country, str) or effective_country.upper() != "DE":
        return {
            "status": "unsupported", "data_quality": "no_live_offers",
            "price_comparison": False, "offers": [], "total_offers": 0,
            "best_price": None, "best_deal": None,
            "error": "Nur Deutschland (DE) wird unterstützt; Fremdwährungen und Auslandsangebote sind nicht verifiziert.",
        }
    if not isinstance(query, str) or not query.strip() or len(query) > 240:
        return {
            "status": "invalid_query", "data_quality": "no_live_offers",
            "price_comparison": False, "offers": [], "total_offers": 0,
            "best_price": None, "best_deal": None,
            "error": "Produkt-Suchbegriff muss 1 bis 240 Zeichen enthalten.",
        }
    if isinstance(max_offers, bool) or not isinstance(max_offers, int) or not 1 <= max_offers <= 10:
        return {
            "status": "invalid_argument", "data_quality": "no_live_offers",
            "price_comparison": False, "offers": [], "total_offers": 0,
            "best_price": None, "best_deal": None,
            "error": "max_offers muss eine ganze Zahl zwischen 1 und 10 sein.",
        }
    if sort_by != "price_asc":
        return {
            "status": "unsupported", "data_quality": "no_live_offers",
            "price_comparison": False, "offers": [], "total_offers": 0,
            "best_price": None, "best_deal": None,
            "error": "Nur Sortierung nach Suchtrefferpreis (price_asc) unterstützt.",
        }
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1.0 <= float(timeout) <= 15.0:
        return {
            "status": "invalid_argument", "data_quality": "no_live_offers",
            "price_comparison": False, "offers": [], "total_offers": 0,
            "best_price": None, "best_deal": None,
            "error": "timeout muss zwischen 1 und 15 Sekunden liegen.",
        }
    clean_query = query.strip().rstrip("?.!")
    clean_query = re.sub(r"^(?:das|ein|eine|einen|der|die|den|dem|für|fuer|von)\s+", "", clean_query, flags=re.IGNORECASE).strip()
    clean_query = re.sub(r"(?:\s+durch|\s+durchführen|\s+machen)?\s*(?:und\s+zeige.*|und\s+stelle.*|und\s+bereite.*|in\s+einer\s+tabelle.*|tabelle.*|im\s+vergleich.*|kaufen.*|online.*|am\s+günstigsten.*)$", "", clean_query, flags=re.IGNORECASE).strip()
    clean_query = re.sub(r"\s+", " ", clean_query).strip()
    if not clean_query:
        return {"error": "Suchbegriff für Produktvergleich darf nicht leer sein."}

    # 1. Check live search
    raw_offers = fetch_live_shopping_offers(clean_query, timeout=timeout)
    # The fetcher is not a source of verified offers. Validate even mocked or
    # upstream-supplied results before any numeric aggregation or display.
    offers: list[dict[str, Any]] = []
    if isinstance(raw_offers, list):
        for item in raw_offers:
            if not isinstance(item, dict):
                continue
            value = item.get("price")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            try:
                amount = float(value)
            except (OverflowError, ValueError):
                continue
            if not math.isfinite(amount) or amount <= 0:
                continue
            if not isinstance(item.get("url"), str) or _safe_offer_host(item["url"]) is None:
                continue
            offers.append({**item, "price": round(amount, 2)})

    # No live-search result is preferable to presenting invented market data.
    # Retain the existing response keys for callers, but use nulls for unknown
    # prices instead of implying zero-cost or synthetic merchant inventory.
    if not offers:
        prod_title = clean_query.title()
        return {
            "status": "unavailable",
            "data_quality": "no_live_offers",
            "error": "Keine aktuellen Preisangaben in Suchtreffern gefunden; Händlerpreise und Verfügbarkeit sind nicht bestätigt.",
            "product_name": prod_title,
            "product": prod_title,
            "query": clean_query,
            "price_comparison": False,
            "best_price": None,
            "best_merchant": None,
            "best_deal": None,
            "currency": "EUR",
            "average_price": None,
            "max_price": None,
            "max_savings_val": None,
            "savings_max": None,
            "max_savings_percent": None,
            "savings_percent": None,
            "offers_count": 0,
            "total_offers": 0,
            "offers": [],
            "country": effective_country,
            "category": category or "Allgemein",
        }

    # Shipping cost is unknown unless the snippet explicitly mentions free shipping.
    # Do not invent total costs or merchant star ratings.
    for o in offers:
        p = float(o.get("price", 0.0))
        # Even snippet-based "free shipping" is unconfirmed; total cost remains unknown.
        o["total_price"] = None
        o.pop("rating", None)
        o["source"] = "search_snippet_unverified"
        o["verified"] = False

    # Sort only by the extracted product price; shipping may be unknown.
    offers.sort(key=lambda x: float(x.get("price", 999999.0)))
    offers = offers[:max_offers]

    for idx, o in enumerate(offers, 1):
        o["rank"] = idx

    prices = [float(o["price"]) for o in offers if o.get("price") is not None]
    best_p = min(prices) if prices else 0.0
    max_p = max(prices) if prices else 0.0
    avg_p = round(sum(prices) / len(prices), 2) if prices else 0.0
    # A difference between unverified snippet prices is not verified savings.
    savings_val = None
    savings_pct = None

    # Leave the conventional "best" fields empty so consumers which ignore
    # data_quality cannot silently display unverified values as confirmed offers.
    best_merchant = None
    best_deal = None

    # Derive clean title
    prod_title = clean_query.title()

    return {
        "status": "unverified",
        "data_quality": "search_snippet_unverified",
        "pricing_excludes_unverified_shipping": True,
        "product_name": prod_title,
        "product": prod_title,
        "query": clean_query,
        "price_comparison": False,
        "best_price": None,
        "best_merchant": best_merchant,
        "best_deal": best_deal,
        "unverified_lowest_price": best_p,
        "unverified_highest_price": max_p,
        "unverified_average_price": avg_p,
        "currency": offers[0].get("currency", "EUR") if offers else "EUR",
        "average_price": None,
        "max_price": None,
        "unverified_price_range": round(max_p - best_p, 2),
        "max_savings_val": savings_val,
        "savings_max": savings_val,
        "max_savings_percent": savings_pct,
        "savings_percent": savings_pct,
        "offers_count": len(offers),
        "total_offers": len(offers),
        "offers": offers,
        "country": effective_country,
        "category": category or "Allgemein",
    }