# SPDX-License-Identifier: Apache-2.0
"""
Currency & Cryptocurrency Conversion Tool.
Provides real-time exchange rates for global fiat currencies and cryptocurrencies.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"

# Standard fallback fiat rates (relative to EUR) in case public API is momentarily unreachable
FALLBACK_RATES_TO_EUR: Dict[str, float] = {
    "EUR": 1.0,
    "USD": 1.085,
    "GBP": 0.855,
    "CHF": 0.945,
    "JPY": 165.20,
    "CAD": 1.485,
    "AUD": 1.660,
    "CNY": 7.820,
    "PLN": 4.280,
    "SEK": 11.35,
    "NOK": 11.60,
    "TRY": 37.10,
    "INR": 90.80,
    "BRL": 6.10,
}

CURRENCY_ALIASES: Dict[str, str] = {
    "euro": "EUR",
    "dollar": "USD",
    "us-dollar": "USD",
    "us dollar": "USD",
    "usd": "USD",
    "eur": "EUR",
    "pfund": "GBP",
    "britisches pfund": "GBP",
    "pound": "GBP",
    "gbp": "GBP",
    "franken": "CHF",
    "schweizer franken": "CHF",
    "chf": "CHF",
    "yen": "JPY",
    "japanischer yen": "JPY",
    "jpy": "JPY",
    "yuan": "CNY",
    "renminbi": "CNY",
    "cny": "CNY",
    "rubel": "RUB",
    "rub": "RUB",
    "kanadischer dollar": "CAD",
    "cad": "CAD",
    "australischer dollar": "AUD",
    "aud": "AUD",
    "zloty": "PLN",
    "pln": "PLN",
    "krone": "SEK",
    "schwedische krone": "SEK",
    "sek": "SEK",
    "norwegische krone": "NOK",
    "nok": "NOK",
    "lira": "TRY",
    "türkische lira": "TRY",
    "try": "TRY",
    "rupie": "INR",
    "indische rupie": "INR",
    "inr": "INR",
    "real": "BRL",
    "brasilianischer real": "BRL",
    "brl": "BRL",
    "bitcoin": "BTC",
    "btc": "BTC",
    "ethereum": "ETH",
    "eth": "ETH",
    "solana": "SOL",
    "sol": "SOL",
    "ripple": "XRP",
    "xrp": "XRP",
    "dogecoin": "DOGE",
    "doge": "DOGE",
    "cardano": "ADA",
    "ada": "ADA",
    "binance coin": "BNB",
    "bnb": "BNB",
}

CRYPTO_MAP: Dict[str, str] = {
    "BTC": "bitcoin",
    "BITCOIN": "bitcoin",
    "ETH": "ethereum",
    "ETHEREUM": "ethereum",
    "SOL": "solana",
    "SOLANA": "solana",
    "XRP": "ripple",
    "RIPPLE": "ripple",
    "DOGE": "dogecoin",
    "DOGECOIN": "dogecoin",
    "ADA": "cardano",
    "CARDANO": "cardano",
    "BNB": "binancecoin",
}


def _resolve_currency_code(code_or_name: str) -> str:
    cleaned = code_or_name.strip().lower()
    return CURRENCY_ALIASES.get(cleaned, code_or_name.strip().upper())


def _fetch_frankfurter(amount: float, from_curr: str, to_curr: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """Fetches ECB exchange rate from public Frankfurter API."""
    url = f"https://api.frankfurter.app/latest?amount={amount}&from={from_curr}&to={to_curr}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "rates" in data and to_curr in data["rates"]:
                converted = float(data["rates"][to_curr])
                rate = round(converted / amount, 6) if amount != 0 else 0.0
                return {
                    "amount": amount,
                    "from_currency": from_curr,
                    "to_currency": to_curr,
                    "converted_amount": round(converted, 4),
                    "rate": rate,
                    "date": data.get("date", ""),
                    "source": "European Central Bank (Frankfurter)",
                }
    except Exception:
        pass
    return None


def _fetch_coingecko_crypto(symbol: str, target_curr: str = "USD", timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """Fetches live crypto price from CoinGecko API."""
    coin_id = CRYPTO_MAP.get(symbol.upper())
    if not coin_id:
        return None
    target_clean = target_curr.lower()
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={target_clean}&include_24hr_change=true"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if coin_id in data and target_clean in data[coin_id]:
                price = float(data[coin_id][target_clean])
                change_24h = data[coin_id].get(f"{target_clean}_24h_change")
                return {
                    "coin": coin_id,
                    "symbol": symbol.upper(),
                    "price": price,
                    "vs_currency": target_curr.upper(),
                    "change_24h_percent": round(change_24h, 2) if change_24h is not None else None,
                    "source": "CoinGecko",
                }
    except Exception:
        pass
    return None


def _convert_single_pair(amount: float, from_c: str, to_c: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Converts a single currency pair with fallbacks."""
    from_c = _resolve_currency_code(from_c)
    to_c = _resolve_currency_code(to_c)

    if from_c == to_c:
        return {
            "amount": amount,
            "from_currency": from_c,
            "to_currency": to_c,
            "converted_amount": amount,
            "rate": 1.0,
            "formatted": f"{amount:,.2f} {from_c} = {amount:,.2f} {to_c}",
            "source": "Identical currency",
        }

    # Check crypto conversion
    if from_c in CRYPTO_MAP:
        crypto_res = _fetch_coingecko_crypto(from_c, target_curr=to_c, timeout=timeout)
        if crypto_res:
            unit_price = crypto_res["price"]
            total_converted = round(amount * unit_price, 4 if unit_price < 100 else 2)
            return {
                "amount": amount,
                "from_currency": from_c,
                "to_currency": to_c,
                "converted_amount": total_converted,
                "rate": unit_price,
                "change_24h_percent": crypto_res.get("change_24h_percent"),
                "formatted": f"{amount} {from_c} = {total_converted:,.2f} {to_c} (1 {from_c} = {unit_price:,.2f} {to_c})",
                "source": "CoinGecko Live Crypto API",
            }

    if to_c in CRYPTO_MAP:
        crypto_res = _fetch_coingecko_crypto(to_c, target_curr=from_c, timeout=timeout)
        if crypto_res:
            unit_price = crypto_res["price"]
            total_converted = round(amount / unit_price, 6) if unit_price > 0 else 0.0
            return {
                "amount": amount,
                "from_currency": from_c,
                "to_currency": to_c,
                "converted_amount": total_converted,
                "rate": round(1.0 / unit_price, 6) if unit_price > 0 else 0.0,
                "formatted": f"{amount:,.2f} {from_c} = {total_converted} {to_c} (1 {to_c} = {unit_price:,.2f} {from_c})",
                "source": "CoinGecko Live Crypto API",
            }

    # Fiat conversion via Frankfurter ECB API
    fiat_res = _fetch_frankfurter(amount, from_c, to_c, timeout=timeout)
    if fiat_res:
        conv_val = fiat_res["converted_amount"]
        fiat_res["formatted"] = f"{amount:,.2f} {from_c} = {conv_val:,.2f} {to_c} (Kurs: 1 {from_c} = {fiat_res['rate']} {to_c})"
        return fiat_res

    # Fallback calculation using reference rates
    if from_c in FALLBACK_RATES_TO_EUR and to_c in FALLBACK_RATES_TO_EUR:
        eur_amount = amount / FALLBACK_RATES_TO_EUR[from_c]
        target_val = round(eur_amount * FALLBACK_RATES_TO_EUR[to_c], 4)
        rate = round(target_val / amount, 6) if amount != 0 else 0.0
        return {
            "amount": amount,
            "from_currency": from_c,
            "to_currency": to_c,
            "converted_amount": target_val,
            "rate": rate,
            "formatted": f"{amount:,.2f} {from_c} ≈ {target_val:,.2f} {to_c} (Referenzkurs: 1 {from_c} ≈ {rate} {to_c})",
            "source": "ECB Reference Table Fallback",
            "note": "Live-Abfrage kurzzeitig nicht erreichbar; stabiler EZB-Referenzkurs verwendet.",
        }

    return {
        "error": f"Währungsumrechnung von '{from_c}' in '{to_c}' nicht möglich.",
        "amount": amount,
        "from_currency": from_c,
        "to_currency": to_c,
    }


def convert_currency(
    amount: float = 1.0,
    from_currency: str = "EUR",
    to_currency: str = "USD",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Converts amounts between fiat currencies (EUR, USD, GBP, CHF, JPY, etc.) or cryptocurrencies (BTC, ETH, SOL).
    Supports multiple destination currencies (e.g. 'USD, GBP, JPY' or query '100 EUR in USD und CHF').
    """
    # Parse query if provided (e.g. "100 EUR in USD, GBP und JPY")
    if query:
        # Pattern 1: amount + from + in/to + target list
        m = re.search(r"([\d.,]+)\s*([A-Za-zäöüÄÖÜß\s\-]{3,20})\s*(?:in|to|zu|nach)\s*(.+)", query, re.IGNORECASE)
        if m:
            try:
                amount = float(m.group(1).replace(",", "."))
                from_currency = m.group(2).strip()
                to_currency = m.group(3).strip()
            except ValueError:
                pass
        else:
            # Pattern 2: "Wie viel sind 100 Euro in Dollar und Yen"
            m2 = re.search(r"(?:wie\s+viel(?:e)?\s+sind\s+)?([\d.,]+)\s*([A-Za-zäöüÄÖÜß\s\-]+?)\s*(?:in|to|zu|nach)\s*(.+)", query, re.IGNORECASE)
            if m2:
                try:
                    amount = float(m2.group(1).replace(",", "."))
                    from_currency = m2.group(2).strip()
                    to_currency = m2.group(3).strip()
                except ValueError:
                    pass

    try:
        clean_amount = float(amount)
    except (ValueError, TypeError):
        return {"error": f"Ungültiger Betrag '{amount}'. Bitte eine Zahl angeben."}

    if clean_amount < 0:
        return {"error": "Betrag muss positiv sein."}
    if clean_amount > 1e15:
        return {"error": "Betrag überschreitet das zulässige Limit (1e15)."}

    from_c = _resolve_currency_code(from_currency or "EUR")
    to_str = (to_currency or "USD").strip()

    # Split multiple destination currencies (e.g. "USD, GBP und JPY", "USD & CHF")
    raw_targets = []
    for t in re.split(r'\s+(?:und|and|&|\+|,|sowie)\s+|,\s*', to_str, flags=re.IGNORECASE):
        t_clean = t.strip().rstrip("?.!")
        t_clean = re.sub(r"\s+(?:um|bitte|jetzt|mal|fuer|für|in)$", "", t_clean, flags=re.IGNORECASE).strip()
        if t_clean:
            raw_targets.append(t_clean)
    target_currencies = [_resolve_currency_code(t) for t in raw_targets if len(t) >= 2]

    if len(target_currencies) > 1:
        conversions = []
        for dst_c in target_currencies:
            res = _convert_single_pair(clean_amount, from_c, dst_c, timeout=timeout / 2)
            conversions.append(res)
        return {
            "multiple_conversions": True,
            "amount": clean_amount,
            "from_currency": from_c,
            "conversions": conversions,
            "count": len(conversions),
        }

    target_curr = target_currencies[0] if target_currencies else "USD"
    return _convert_single_pair(clean_amount, from_c, target_curr, timeout=timeout)


# Backwards-compatible alias
calculate_currency_exchange = convert_currency
