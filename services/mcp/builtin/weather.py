# SPDX-License-Identifier: Apache-2.0
"""
Live Weather & Meteorological Data Tool.
Fetches real-time weather, temperature, humidity, wind, and conditions worldwide via Open-Meteo & wttr.in.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2"

# WMO Weather interpretation codes (WW)
WMO_WEATHER_CODES = {
    0: "Klarer Himmel / Sonnig",
    1: "Hauptsächlich klar",
    2: "Teilweise bewölkt",
    3: "Bedeckt / Bewölkt",
    45: "Nebel",
    48: "Ablagernder Reifnebel",
    51: "Leichter Nieselregen",
    53: "Mäßiger Nieselregen",
    55: "Dichter Nieselregen",
    56: "Leichter gefrierender Nieselregen",
    57: "Dichter gefrierender Nieselregen",
    61: "Leichter Regen",
    63: "Mäßiger Regen",
    65: "Starker Regen",
    66: "Leichter gefrierender Regen",
    67: "Starker gefrierender Regen",
    71: "Leichter Schneefall",
    73: "Mäßiger Schneefall",
    75: "Starker Schneefall",
    77: "Schneegriesel",
    80: "Leichte Regenschauer",
    81: "Mäßige Regenschauer",
    82: "Heftige Regenschauer",
    85: "Leichte Schneeschauer",
    86: "Starke Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit leichtem Hagel",
    99: "Gewitter mit schwerem Hagel",
}


def geocode_location(location_name: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Resolves city/place name to coordinates using Open-Meteo Geocoding API."""
    encoded = urllib.parse.quote(location_name.strip())
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=1&language=de&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results")
        if results and len(results) > 0:
            top = results[0]
            return {
                "name": top.get("name"),
                "latitude": top.get("latitude"),
                "longitude": top.get("longitude"),
                "country": top.get("country", ""),
                "admin1": top.get("admin1", ""),
            }
    except Exception:
        pass
    return None


def fetch_open_meteo_weather(lat: float, lon: float, location_meta: Dict[str, Any], timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Fetches real-time current weather metrics from Open-Meteo Forecast API."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
        "&timezone=auto"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        current = data.get("current", {})
        code = current.get("weather_code", 0)
        condition_str = WMO_WEATHER_CODES.get(code, "Unbekannt")

        return {
            "location": location_meta.get("name"),
            "region": location_meta.get("admin1"),
            "country": location_meta.get("country"),
            "temperature_celsius": current.get("temperature_2m"),
            "apparent_temperature_celsius": current.get("apparent_temperature"),
            "condition": condition_str,
            "humidity_percent": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "source": "Open-Meteo",
        }
    except Exception:
        return None


def fetch_wttr_weather(location_name: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    """Fallback weather fetcher using wttr.in JSON API."""
    encoded = urllib.parse.quote(location_name.strip())
    url = f"https://wttr.in/{encoded}?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        current_cond = data.get("current_condition", [{}])[0]
        nearest_area = data.get("nearest_area", [{}])[0]
        area_name = nearest_area.get("areaName", [{}])[0].get("value", location_name)
        country = nearest_area.get("country", [{}])[0].get("value", "")

        return {
            "location": area_name,
            "country": country,
            "temperature_celsius": float(current_cond.get("temp_C", 0)),
            "apparent_temperature_celsius": float(current_cond.get("FeelsLikeC", 0)),
            "condition": current_cond.get("weatherDesc", [{}])[0].get("value", ""),
            "humidity_percent": int(current_cond.get("humidity", 0)),
            "precipitation_mm": float(current_cond.get("precipMM", 0)),
            "wind_speed_kmh": float(current_cond.get("windspeedKmph", 0)),
            "source": "wttr.in",
        }
    except Exception:
        return None


def get_current_weather(
    location: str = "",
    city: str = "",
    place: str = "",
    query: str = "",
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    Returns real-time live weather information, temperature, humidity, wind, and conditions for any city or location worldwide.
    """
    target = (location or city or place or query or "").strip()
    if not target:
        return {"error": "Ort oder Stadt darf nicht leer sein (z. B. 'Veitshöchheim', 'Würzburg', 'Berlin', 'München')."}

    # 1. Primary: Open-Meteo Geocoding + Precise Hourly Weather
    geo = geocode_location(target, timeout=timeout / 2)
    if geo and geo.get("latitude") is not None and geo.get("longitude") is not None:
        weather_data = fetch_open_meteo_weather(geo["latitude"], geo["longitude"], geo, timeout=timeout / 2)
        if weather_data:
            return weather_data

    # 2. Fallback: wttr.in
    wttr_data = fetch_wttr_weather(target, timeout=timeout / 2)
    if wttr_data:
        return wttr_data

    return {
        "error": f"Keine aktuellen Wetterdaten für '{target}' gefunden. Bitte Ortsnamen überprüfen.",
        "location": target,
    }


# Backwards-compatible alias
execute_get_weather = get_current_weather
