# SPDX-License-Identifier: Apache-2.0
"""
Country, Demographics & Geographic Intelligence Tool.
Fetches verified data about nations worldwide (capital, population, currencies, languages, borders, timezones) via REST Countries API.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def lookup_country_data(
    country: str = "",
    name: str = "",
    query: str = "",
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Fetches verified geographical, demographic, and political data for any country worldwide.
    """
    search_term = (country or name or query or "").strip()
    if not search_term:
        return {"error": "Ländername oder Suchbegriff darf nicht leer sein (z. B. 'Deutschland', 'Germany', 'Japan', 'Brasilien')."}

    # Common German-to-English country translations for high match rate
    TRANSLATIONS = {
        "deutschland": "germany",
        "österreich": "austria",
        "schweiz": "switzerland",
        "frankreich": "france",
        "italien": "italy",
        "spanien": "spain",
        "vereinigte staaten": "usa",
        "vereinigtes königreich": "united kingdom",
        "england": "united kingdom",
        "großbritannien": "united kingdom",
        "russland": "russia",
        "china": "china",
        "japan": "japan",
        "brasilien": "brazil",
        "indien": "india",
        "schweden": "sweden",
        "norwegen": "norway",
        "dänemark": "denmark",
        "niederlande": "netherlands",
        "holland": "netherlands",
        "polen": "poland",
        "tschechien": "czechia",
        "griechenland": "greece",
        "türkei": "turkey",
        "südkorea": "south korea",
        "ägypten": "egypt",
        "südafrika": "south africa",
        "kanada": "canada",
        "mexiko": "mexico",
        "australien": "australia",
    }

    lookup_name = TRANSLATIONS.get(search_term.lower(), search_term)
    encoded = urllib.parse.quote(lookup_name)
    url = f"https://restcountries.com/v3.1/name/{encoded}?fields=name,capital,population,region,subregion,currencies,languages,borders,timezones,area,flags,car"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not data or not isinstance(data, list):
            return {"error": f"Keine Länderdaten für '{search_term}' gefunden."}

        item = data[0]
        common_name = item.get("name", {}).get("common", search_term)
        official_name = item.get("name", {}).get("official", common_name)
        german_name = item.get("name", {}).get("nativeName", {}).get("deu", {}).get("common", common_name)

        capitals = item.get("capital", [])
        capital_str = ", ".join(capitals) if capitals else "Keine Angabe"

        currencies_dict = item.get("currencies", {})
        curr_list = [f"{v.get('name', k)} ({k}, Symbol: {v.get('symbol', '')})" for k, v in currencies_dict.items()]

        langs_dict = item.get("languages", {})
        languages = list(langs_dict.values())

        population = item.get("population", 0)
        area_sqkm = item.get("area", 0)
        borders = item.get("borders", [])
        timezones = item.get("timezones", [])

        summary = (
            f"**{common_name}** ({official_name}):\n"
            f"- **Hauptstadt**: {capital_str}\n"
            f"- **Region**: {item.get('region', '')} ({item.get('subregion', '')})\n"
            f"- **Einwohnerzahl**: {population:,} Menschen\n"
            f"- **Fläche**: {area_sqkm:,} km²\n"
            f"- **Währung(en)**: {', '.join(curr_list) if curr_list else 'Unbekannt'}\n"
            f"- **Amtssprache(n)**: {', '.join(languages) if languages else 'Unbekannt'}\n"
            f"- **Nachbarländer (Grenz-Codes)**: {', '.join(borders) if borders else 'Inselstaat / Keine Landgrenzen'}\n"
            f"- **Zeitzonen**: {', '.join(timezones[:4])}"
        )

        return {
            "country_name": common_name,
            "official_name": official_name,
            "capital": capital_str,
            "population": population,
            "area_sqkm": area_sqkm,
            "region": item.get("region", ""),
            "subregion": item.get("subregion", ""),
            "currencies": currencies_dict,
            "languages": languages,
            "borders": borders,
            "timezones": timezones,
            "summary": summary,
            "flag_png": item.get("flags", {}).get("png", ""),
        }
    except Exception as e:
        return {"error": f"Länderdatenbank-Abfrage für '{search_term}' fehlgeschlagen: {str(e)}"}


# Backwards-compatible alias
get_country_info = lookup_country_data
