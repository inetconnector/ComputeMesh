# SPDX-License-Identifier: Apache-2.0
"""
Country, Demographics & Geographic Intelligence Tool.
Fetches verified data about nations worldwide (capital, population, region, coordinates, ISO codes) via World Bank & Wikipedia.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"

COUNTRY_NAME_TO_ISO3: Dict[str, str] = {
    "deutschland": "DEU",
    "germany": "DEU",
    "de": "DEU",
    "österreich": "AUT",
    "austria": "AUT",
    "at": "AUT",
    "schweiz": "CHE",
    "switzerland": "CHE",
    "ch": "CHE",
    "frankreich": "FRA",
    "france": "FRA",
    "fr": "FRA",
    "italien": "ITA",
    "italy": "ITA",
    "it": "ITA",
    "spanien": "ESP",
    "spain": "ESP",
    "es": "ESP",
    "portugal": "PRT",
    "pt": "PRT",
    "vereinigte staaten": "USA",
    "vereinigte staaten von amerika": "USA",
    "usa": "USA",
    "us": "USA",
    "united states": "USA",
    "amerika": "USA",
    "vereinigtes königreich": "GBR",
    "england": "GBR",
    "großbritannien": "GBR",
    "uk": "GBR",
    "united kingdom": "GBR",
    "japan": "JPN",
    "jp": "JPN",
    "china": "CHN",
    "cn": "CHN",
    "volksrepublik china": "CHN",
    "brasilien": "BRA",
    "brazil": "BRA",
    "br": "BRA",
    "indien": "IND",
    "india": "IND",
    "in": "IND",
    "kanada": "CAN",
    "canada": "CAN",
    "ca": "CAN",
    "australien": "AUS",
    "australia": "AUS",
    "au": "AUS",
    "neuseeland": "NZL",
    "new zealand": "NZL",
    "mexiko": "MEX",
    "mexico": "MEX",
    "mx": "MEX",
    "argentinien": "ARG",
    "argentina": "ARG",
    "ar": "ARG",
    "südafrika": "ZAF",
    "south africa": "ZAF",
    "za": "ZAF",
    "ägypten": "EGY",
    "egypt": "EGY",
    "eg": "EGY",
    "südkorea": "KOR",
    "south korea": "KOR",
    "korea": "KOR",
    "kr": "KOR",
    "polen": "POL",
    "poland": "POL",
    "pl": "POL",
    "niederlande": "NLD",
    "netherlands": "NLD",
    "holland": "NLD",
    "nl": "NLD",
    "belgien": "BEL",
    "belgium": "BEL",
    "be": "BEL",
    "schweden": "SWE",
    "sweden": "SWE",
    "se": "SWE",
    "norwegen": "NOR",
    "norway": "NOR",
    "no": "NOR",
    "dänemark": "DNK",
    "denmark": "DNK",
    "dk": "DNK",
    "finnland": "FIN",
    "finland": "FIN",
    "fi": "FIN",
    "griechenland": "GRC",
    "greece": "GRC",
    "gr": "GRC",
    "türkei": "TUR",
    "turkey": "TUR",
    "tr": "TUR",
    "russland": "RUS",
    "russia": "RUS",
    "ru": "RUS",
    "tschechien": "CZE",
    "czechia": "CZE",
    "cz": "CZE",
    "ungarn": "HUN",
    "hungary": "HUN",
    "hu": "HUN",
    "irland": "IRL",
    "ireland": "IRL",
    "ie": "IRL",
    "indonesien": "IDN",
    "indonesia": "IDN",
    "id": "IDN",
    "saudi-arabien": "SAU",
    "saudi arabia": "SAU",
    "sa": "SAU",
    "singapur": "SGP",
    "singapore": "SGP",
    "sg": "SGP",
    "israel": "ISR",
    "il": "ISR",
    "ukraine": "UKR",
    "ua": "UKR",
}

GERMAN_COUNTRY_NAMES: Dict[str, str] = {
    "DEU": "Deutschland",
    "AUT": "Österreich",
    "CHE": "Schweiz",
    "FRA": "Frankreich",
    "ITA": "Italien",
    "ESP": "Spanien",
    "PRT": "Portugal",
    "USA": "Vereinigte Staaten von Amerika",
    "GBR": "Vereinigtes Königreich",
    "JPN": "Japan",
    "CHN": "China",
    "BRA": "Brasilien",
    "IND": "Indien",
    "CAN": "Kanada",
    "AUS": "Australien",
    "NZL": "Neuseeland",
    "MEX": "Mexiko",
    "ARG": "Argentinien",
    "ZAF": "Südafrika",
    "EGY": "Ägypten",
    "KOR": "Südkorea",
    "POL": "Polen",
    "NLD": "Niederlande",
    "BEL": "Belgien",
    "SWE": "Schweden",
    "NOR": "Norwegen",
    "DNK": "Dänemark",
    "FIN": "Finnland",
    "GRC": "Griechenland",
    "TUR": "Türkei",
    "RUS": "Russland",
    "CZE": "Tschechien",
    "HUN": "Ungarn",
    "IRL": "Irland",
    "IDN": "Indonesien",
    "SAU": "Saudi-Arabien",
    "SGP": "Singapur",
    "ISR": "Israel",
    "UKR": "Ukraine",
}


def _lookup_single_country(search_term: str, timeout: float = 6.0) -> Dict[str, Any]:
    """Fetches verified geographic & demographic data for a single country."""
    clean_term = search_term.strip().lower()
    clean_term = re.sub(r'^(?:über|ueber|von|in|zu|fakten\s+über|fakten\s+zu|daten\s+zu|infos\s+zu|info\s+über|land|das\s+land)\s+', '', clean_term, flags=re.IGNORECASE).strip()

    iso3 = COUNTRY_NAME_TO_ISO3.get(clean_term, clean_term.upper())

    # 1. World Bank Official Country Metadata
    url_wb = f"https://api.worldbank.org/v2/country/{iso3}?format=json"
    req_wb = urllib.request.Request(url_wb, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req_wb, timeout=timeout) as resp:
            data_wb = json.loads(resp.read().decode("utf-8"))

        if not data_wb or not isinstance(data_wb, list) or len(data_wb) < 2 or not data_wb[1]:
            # Fallback to Wikipedia summary
            from .wikipedia import get_wikipedia_summary
            wiki_res = get_wikipedia_summary(query=search_term, timeout=timeout)
            if wiki_res and "error" not in wiki_res:
                return {
                    "country_name": wiki_res.get("title", search_term),
                    "summary": f"**{wiki_res.get('title')}**:\n\n{wiki_res.get('summary', '')}",
                    "source": "Wikipedia",
                }
            return {"error": f"Keine Länderdaten für '{search_term}' gefunden."}

        item = data_wb[1][0]
        country_name_en = item.get("name", search_term)
        country_name_de = GERMAN_COUNTRY_NAMES.get(iso3, country_name_en)
        capital = item.get("capitalCity", "N/A")
        region = item.get("region", {}).get("value", "N/A")
        income = item.get("incomeLevel", {}).get("value", "N/A")
        lat = item.get("latitude")
        lon = item.get("longitude")

        # 2. Fetch Latest Verified Population from World Bank
        population = None
        url_pop = f"https://api.worldbank.org/v2/country/{iso3}/indicator/SP.POP.TOTL?date=2020:2024&format=json"
        req_pop = urllib.request.Request(url_pop, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req_pop, timeout=timeout / 2) as resp_pop:
                pop_data = json.loads(resp_pop.read().decode("utf-8"))
                if pop_data and isinstance(pop_data, list) and len(pop_data) > 1 and pop_data[1]:
                    for p_rec in pop_data[1]:
                        if p_rec.get("value") is not None:
                            population = int(p_rec["value"])
                            break
        except Exception:
            pass

        summary_lines = [
            f"### 🏛️ **{country_name_de}** ({country_name_en}, ISO: `{iso3}`)",
            f"- **Hauptstadt:** {capital}",
            f"- **Region:** {region}",
            f"- **Wirtschaftsklassifizierung:** {income}",
        ]
        if population:
            summary_lines.append(f"- **Einwohnerzahl:** {population:,} Menschen *(Quelle: Weltbank)*")
        if lat and lon:
            summary_lines.append(f"- **Koordinaten (Hauptstadt/Zentrum):** `{lat}° N, {lon}° E`")

        return {
            "country_name": country_name_de,
            "official_name": country_name_en,
            "iso3": iso3,
            "capital": capital,
            "region": region,
            "income_level": income,
            "population": population,
            "latitude": lat,
            "longitude": lon,
            "summary": "\n".join(summary_lines),
            "source": "World Bank Open Data",
        }
    except Exception as e:
        return {"error": f"Länderdaten-Abfrage für '{search_term}' fehlgeschlagen: {str(e)}"}


def lookup_country_data(
    country: str = "",
    name: str = "",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Fetches verified geographical, demographic, and political data for any country worldwide.
    Supports multi-country comparisons (e.g. 'Deutschland, Frankreich, Japan und Brasilien').
    """
    search_term = (country or name or query or "").strip()
    if not search_term:
        return {"error": "Ländername oder Suchbegriff darf nicht leer sein (z. B. 'Deutschland', 'Japan', 'Brasilien')."}

    # Multi-country detection
    raw_countries = [c.strip().rstrip("?.!") for c in re.split(r'\s+(?:und|and|&|\+|,|sowie)\s+|,\s*', search_term, flags=re.IGNORECASE) if c.strip()]
    cleaned_countries = []
    for c in raw_countries:
        clean_c = re.sub(r'^(?:über|ueber|von|in|zu|fakten\s+über|fakten\s+zu|daten\s+zu|infos\s+zu|info\s+über|land|das\s+land)\s+', '', c, flags=re.IGNORECASE).strip()
        if clean_c and len(clean_c) >= 2:
            cleaned_countries.append(clean_c)

    if len(cleaned_countries) > 1:
        countries_data = []
        for single_c in cleaned_countries:
            c_res = _lookup_single_country(single_c, timeout=timeout / 2)
            if c_res and "error" not in c_res:
                countries_data.append(c_res)
        if countries_data:
            if len(countries_data) == 1:
                return countries_data[0]
            return {
                "multiple_countries": True,
                "countries": countries_data,
                "count": len(countries_data)
            }

    return _lookup_single_country(cleaned_countries[0] if cleaned_countries else search_term, timeout=timeout)


# Backwards-compatible alias
get_country_info = lookup_country_data
