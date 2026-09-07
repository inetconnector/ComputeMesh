# SPDX-License-Identifier: Apache-2.0
"""
World Bank Macroeconomic & Development Indicators Tool.
Fetches verified economic, demographic, inflation, and development data for all countries from the World Bank API.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"

COUNTRY_CODES_MAP = {
    "deutschland": "DEU",
    "germany": "DEU",
    "de": "DEU",
    "usa": "USA",
    "vereinigte staaten": "USA",
    "us": "USA",
    "österreich": "AUT",
    "austria": "AUT",
    "schweiz": "CHE",
    "switzerland": "CHE",
    "ch": "CHE",
    "frankreich": "FRA",
    "france": "FRA",
    "fr": "FRA",
    "japan": "JPN",
    "jp": "JPN",
    "china": "CHN",
    "cn": "CHN",
    "großbritannien": "GBR",
    "uk": "GBR",
    "italien": "ITA",
    "spanien": "ESP",
    "indien": "IND",
    "brasilien": "BRA",
    "kanada": "CAN",
    "welt": "WLD",
    "world": "WLD",
}

INDICATORS_MAP = {
    "gdp": ("NY.GDP.MKTP.CD", "Bruttoinlandsprodukt (BIP in USD)"),
    "bip": ("NY.GDP.MKTP.CD", "Bruttoinlandsprodukt (BIP in USD)"),
    "gdp_per_capita": ("NY.GDP.PCAP.CD", "BIP pro Kopf (in USD)"),
    "bip_pro_kopf": ("NY.GDP.PCAP.CD", "BIP pro Kopf (in USD)"),
    "inflation": ("FP.CPI.TOTL.ZG", "Inflationsrate (% jährlich)"),
    "population": ("SP.POP.TOTL", "Gesamtbevölkerung"),
    "bevölkerung": ("SP.POP.TOTL", "Gesamtbevölkerung"),
    "life_expectancy": ("SP.DYN.LE00.IN", "Lebenserwartung bei Geburt (Jahre)"),
    "lebenserwartung": ("SP.DYN.LE00.IN", "Lebenserwartung bei Geburt (Jahre)"),
    "co2": ("EN.ATM.CO2E.PC", "CO2-Emissionen (Tonnen pro Kopf)"),
}


def get_world_bank_stats(
    country: str = "DEU",
    indicator: str = "gdp",
    indicator_code: str = "",
    start_year: int = 2018,
    end_year: int = 2024,
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Fetches official macroeconomic indicators (GDP, inflation, population, life expectancy, CO2) from the World Bank.
    """
    clean_country = (country or "DEU").strip().lower()
    iso3 = COUNTRY_CODES_MAP.get(clean_country, clean_country.upper())

    clean_ind = (indicator or "gdp").strip().lower()
    code, ind_name = INDICATORS_MAP.get(clean_ind, (indicator_code or "NY.GDP.MKTP.CD", "Wirtschaftsindikator"))

    url = f"https://api.worldbank.org/v2/country/{iso3}/indicator/{code}?date={start_year}:{end_year}&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data or not isinstance(data, list) or len(data) < 2:
            return {"error": f"Keine Weltbank-Daten für Land '{country}' und Indikator '{indicator}' gefunden."}

        meta = data[0]
        records = data[1] or []

        time_series: List[Dict[str, Any]] = []
        for r in records:
            val = r.get("value")
            if val is not None:
                time_series.append({
                    "year": r.get("date"),
                    "value": round(val, 2) if isinstance(val, (int, float)) else val,
                })

        country_name = records[0].get("country", {}).get("value", iso3) if records else iso3

        summary_lines = [f"**Weltbank-Statistik: {ind_name} für {country_name} ({iso3})**"]
        for entry in time_series[:5]:
            val_fmt = f"{entry['value']:,.2f}" if isinstance(entry['value'], (int, float)) else str(entry['value'])
            summary_lines.append(f"- **{entry['year']}**: {val_fmt}")

        return {
            "country": country_name,
            "country_code": iso3,
            "indicator": ind_name,
            "indicator_code": code,
            "time_series": time_series,
            "latest_value": time_series[0]["value"] if time_series else None,
            "latest_year": time_series[0]["year"] if time_series else None,
            "summary": "\n".join(summary_lines),
            "source": "World Bank Open Data API",
        }
    except Exception as e:
        return {"error": f"Fehler bei Abfrage der Weltbank-Datenbank: {str(e)}"}


# Backwards-compatible alias
lookup_economic_data = get_world_bank_stats
