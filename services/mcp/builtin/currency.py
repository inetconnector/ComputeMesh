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
from typing import Any, Dict, Optional

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

CRYPTO_MAP = {
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


def convert_currency(
    amount: float = 1.0,
    from_currency: str = "EUR",
    to_currency: str = "USD",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Converts amounts between fiat currencies (EUR, USD, GBP, CHF, JPY, etc.) or cryptocurrencies (BTC, ETH, SOL).
    """
    # Parse query if provided (e.g. "100 EUR in USD" or "5 BTC to EUR")
    if query:
        m = re.search(r"([\d.,]+)\s*([A-Za-z]{3,10})\s*(?:in|to|zu|nach)\s*([A-Za-z]{3,10})", query, re.IGNORECASE)
        if m:
            try:
                amount = float(m.group(1).replace(",", "."))
                from_currency = m.group(2).upper()
                to_currency = m.group(3).upper()
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

    from_c = (from_currency or "EUR").strip().upper()
    to_c = (to_currency or "USD").strip().upper()

    # If identical currency
    if from_c == to_c:
        return {
            "amount": clean_amount,
            "from_currency": from_c,
            "to_currency": to_c,
            "converted_amount": clean_amount,
            "rate": 1.0,
            "formatted": f"{clean_amount} {from_c} = {clean_amount} {to_c}",
            "source": "Identical currency",
        }

    # Check for crypto conversions
    if from_c in CRYPTO_MAP:
        crypto_res = _fetch_coingecko_crypto(from_c, target_curr=to_c, timeout=timeout)
        if crypto_res:
            unit_price = crypto_res["price"]
            total_converted = round(clean_amount * unit_price, 4 if unit_price < 100 else 2)
            return {
                "amount": clean_amount,
                "from_currency": from_c,
                "to_currency": to_c,
                "converted_amount": total_converted,
                "unit_price": unit_price,
                "change_24h_percent": crypto_res.get("change_24h_percent"),
                "formatted": f"{clean_amount} {from_c} = {total_converted:,.2f} {to_c} (1 {from_c} = {unit_price:,.2f} {to_c})",
                "source": "CoinGecko Live Crypto API",
            }

    if to_c in CRYPTO_MAP:
        crypto_res = _fetch_coingecko_crypto(to_c, target_curr=from_c, timeout=timeout)
        if crypto_res:
            unit_price = crypto_res["price"]
            total_converted = round(clean_amount / unit_price, 6) if unit_price > 0 else 0.0
            return {
                "amount": clean_amount,
                "from_currency": from_c,
                "to_currency": to_c,
                "converted_amount": total_converted,
                "unit_price": unit_price,
                "formatted": f"{clean_amount} {from_c} = {total_converted} {to_c} (1 {to_c} = {unit_price:,.2f} {from_c})",
                "source": "CoinGecko Live Crypto API",
            }

    # Fiat conversion via Frankfurter ECB API
    fiat_res = _fetch_frankfurter(clean_amount, from_c, to_c, timeout=timeout)
    if fiat_res:
        conv_val = fiat_res["converted_amount"]
        fiat_res["formatted"] = f"{clean_amount:,.2f} {from_c} = {conv_val:,.2f} {to_c} (Kurs: 1 {from_c} = {fiat_res['rate']} {to_c})"
        return fiat_res

    # Fallback calculation using reference rates
    if from_c in FALLBACK_RATES_TO_EUR and to_c in FALLBACK_RATES_TO_EUR:
        eur_amount = clean_amount / FALLBACK_RATES_TO_EUR[from_c]
        target_val = round(eur_amount * FALLBACK_RATES_TO_EUR[to_c], 4)
        rate = round(target_val / clean_amount, 6) if clean_amount != 0 else 0.0
        return {
            "amount": clean_amount,
            "from_currency": from_c,
            "to_currency": to_c,
            "converted_amount": target_val,
            "rate": rate,
            "formatted": f"{clean_amount:,.2f} {from_c} ≈ {target_val:,.2f} {to_c} (Referenzkurs: 1 {from_c} ≈ {rate} {to_c})",
            "source": "ECB Reference Table Fallback",
            "note": "Live-Abfrage kurzzeitig nicht erreichbar; stabiler EZB-Referenzkurs verwendet.",
        }

    return {
        "error": f"Währungsumrechnung von '{from_c}' in '{to_c}' nicht möglich. Unterstützte Währungen: EUR, USD, GBP, CHF, JPY, CAD, AUD, CNY, BTC, ETH, SOL u.v.m.",
        "amount": clean_amount,
        "from_currency": from_c,
        "to_currency": to_c,
    }


# Backwards-compatible alias
calculate_currency_exchange = convert_currency
