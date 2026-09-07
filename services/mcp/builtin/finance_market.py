# SPDX-License-Identifier: Apache-2.0
"""
Live Financial Market & Stock Quotes Tool.
Supports Global Stocks, ETFs, Indices, Crypto, and Currencies.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2"

# Well-known Crypto ticker mappings
CRYPTO_MAPPINGS = {
    "BTC": "bitcoin",
    "BITCOIN": "bitcoin",
    "ETH": "ethereum",
    "ETHEREUM": "ethereum",
    "SOL": "solana",
    "SOLANA": "solana",
    "XRP": "ripple",
    "RIPPLE": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
}


def fetch_yahoo_quote(symbol: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """
    Fetches real-time market data from Yahoo Finance API.
    """
    symbol = symbol.strip().upper()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=1d"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        chart = data.get("chart", {})
        result_list = chart.get("result", [])
        if not result_list:
            return None

        meta = result_list[0].get("meta", {})
        regular_price = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        currency = meta.get("currency", "USD")
        short_name = meta.get("shortName") or meta.get("symbol", symbol)
        exchange = meta.get("exchangeName", "")
        day_high = meta.get("regularMarketDayHigh")
        day_low = meta.get("regularMarketDayLow")

        change = 0.0
        change_pct = 0.0
        if regular_price is not None and prev_close is not None and prev_close > 0:
            change = regular_price - prev_close
            change_pct = (change / prev_close) * 100.0

        return {
            "symbol": symbol,
            "name": short_name,
            "price": regular_price,
            "currency": currency,
            "change": round(change, 4),
            "change_percent": round(change_pct, 2),
            "previous_close": prev_close,
            "day_high": day_high,
            "day_low": day_low,
            "exchange": exchange,
            "market_state": meta.get("tradingPeriods", [[]])[0][0].get("state", "REGULAR") if meta.get("tradingPeriods") else "REGULAR",
        }
    except Exception:
        return None


def fetch_coingecko_quote(coin_id: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    """
    Fetches cryptocurrency price from CoinGecko public API.
    """
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={urllib.parse.quote(coin_id)}&vs_currencies=usd,eur&include_24hr_change=true"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        coin_data = data.get(coin_id, {})
        if not coin_data:
            return None

        price_usd = coin_data.get("usd")
        price_eur = coin_data.get("eur")
        change_24h = coin_data.get("usd_24h_change")

        return {
            "symbol": coin_id.upper(),
            "name": coin_id.capitalize(),
            "price_usd": price_usd,
            "price_eur": price_eur,
            "change_24h_percent": round(change_24h, 2) if change_24h is not None else 0.0,
            "source": "coingecko",
        }
    except Exception:
        return None


def execute_finance_quote(symbol: str, timeout: float = 10.0) -> Dict[str, Any]:
    """
    Unified financial quote tool. Automatically resolves stocks, indices, and crypto.
    """
    raw_sym = (symbol or "").strip()
    if not raw_sym:
        return {"error": "Symbol darf nicht leer sein (z.B. AAPL, NVDA, BTC, DAX)"}

    clean_sym = raw_sym.upper().replace(" ", "")

    # Check if query is a crypto symbol
    if clean_sym in CRYPTO_MAPPINGS or clean_sym.endswith("-USD") or clean_sym.endswith("USDT"):
        crypto_id = CRYPTO_MAPPINGS.get(clean_sym) or clean_sym.lower().split("-")[0]
        crypto_res = fetch_coingecko_quote(crypto_id, timeout=timeout)
        if crypto_res:
            return crypto_res

        # Fallback to Yahoo Finance BTC-USD format
        yahoo_sym = clean_sym if "-" in clean_sym else f"{clean_sym}-USD"
        yahoo_res = fetch_yahoo_quote(yahoo_sym, timeout=timeout)
        if yahoo_res:
            return yahoo_res

    # Check stock / index (e.g. ^GDAXI for DAX, ^GSPC for S&P500)
    symbol_aliases = {
        "DAX": "^GDAXI",
        "SP500": "^GSPC",
        "S&P500": "^GSPC",
        "NASDAQ": "^IXIC",
        "DOW": "^DJI",
        "GOLD": "GC=F",
        "OIL": "CL=F",
    }
    lookup_sym = symbol_aliases.get(clean_sym, clean_sym)

    res = fetch_yahoo_quote(lookup_sym, timeout=timeout)
    if res:
        return res

    # If simple symbol failed, try with common suffixes if German stock (e.g. SAP -> SAP.DE)
    if not "." in clean_sym and len(clean_sym) <= 5:
        de_res = fetch_yahoo_quote(f"{clean_sym}.DE", timeout=timeout)
        if de_res:
            return de_res

    return {
        "error": f"Keine aktuellen Marktdaten für '{raw_sym}' gefunden. Bitte Symbol prüfen (z. B. AAPL, NVDA, SAP.DE, BTC-USD).",
        "symbol": raw_sym,
    }
