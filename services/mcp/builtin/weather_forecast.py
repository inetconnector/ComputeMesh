# SPDX-License-Identifier: Apache-2.0
"""Multi-day weather forecast via Open-Meteo."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict

from .http_json import ProviderError, fetch_json
from .weather import WMO_WEATHER_CODES

GEOCODING_HOST = "geocoding-api.open-meteo.com"
FORECAST_HOST = "api.open-meteo.com"


def _geocode(location: str, timeout: float) -> Dict[str, Any] | None:
    params = urllib.parse.urlencode({
        "name": location,
        "count": 1,
        "language": "de",
        "format": "json",
    })
    payload = fetch_json(
        f"https://{GEOCODING_HOST}/v1/search?{params}",
        allowed_hosts={GEOCODING_HOST},
        timeout=timeout,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list) or not payload["results"]:
        return None
    top = payload["results"][0]
    if not isinstance(top, dict) or top.get("latitude") is None or top.get("longitude") is None:
        return None
    return top


def get_weather_forecast(
    location: str = "",
    days: int = 7,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Return a 1-16 day daily forecast for a named location."""
    target = str(location or "").strip()
    if not target:
        return {"error": "Ort oder Stadt (location) darf nicht leer sein."}
    if len(target) > 200:
        return {"error": "Ortsangabe ist zu lang (maximal 200 Zeichen)."}
    try:
        forecast_days = max(1, min(16, int(days)))
    except (TypeError, ValueError):
        return {"error": "days muss eine ganze Zahl zwischen 1 und 16 sein."}

    try:
        geo = _geocode(target, max(1.0, timeout * 0.35))
    except ProviderError as exc:
        return {"error": str(exc), "provider": "Open-Meteo"}
    if not geo:
        return {"error": f"Ort '{target}' konnte nicht gefunden werden.", "provider": "Open-Meteo"}

    params = urllib.parse.urlencode({
        "latitude": geo["latitude"],
        "longitude": geo["longitude"],
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "sunrise",
            "sunset",
        ]),
        "timezone": "auto",
        "forecast_days": forecast_days,
    })
    try:
        payload = fetch_json(
            f"https://{FORECAST_HOST}/v1/forecast?{params}",
            allowed_hosts={FORECAST_HOST},
            timeout=max(1.0, timeout * 0.65),
        )
    except ProviderError as exc:
        return {"error": str(exc), "provider": "Open-Meteo"}

    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        return {"error": "Open-Meteo lieferte ein unerwartetes Forecast-Format.", "provider": "Open-Meteo"}

    daily = payload["daily"]
    dates = daily.get("time")
    if not isinstance(dates, list):
        return {"error": "Open-Meteo lieferte keine Tagesachse.", "provider": "Open-Meteo"}

    def at(field: str, index: int) -> Any:
        values = daily.get(field)
        return values[index] if isinstance(values, list) and index < len(values) else None

    forecast = []
    for index, day in enumerate(dates[:forecast_days]):
        code = at("weather_code", index)
        forecast.append({
            "date": day,
            "condition": WMO_WEATHER_CODES.get(code, "Unbekannt") if isinstance(code, int) else "Unbekannt",
            "weather_code": code,
            "temperature_max_celsius": at("temperature_2m_max", index),
            "temperature_min_celsius": at("temperature_2m_min", index),
            "precipitation_sum_mm": at("precipitation_sum", index),
            "precipitation_probability_max_percent": at("precipitation_probability_max", index),
            "wind_speed_max_kmh": at("wind_speed_10m_max", index),
            "sunrise": at("sunrise", index),
            "sunset": at("sunset", index),
        })

    return {
        "location": geo.get("name") or target,
        "region": geo.get("admin1"),
        "country": geo.get("country"),
        "latitude": geo.get("latitude"),
        "longitude": geo.get("longitude"),
        "timezone": payload.get("timezone"),
        "days": len(forecast),
        "forecast": forecast,
        "source": "Open-Meteo",
    }
