# SPDX-License-Identifier: Apache-2.0
"""
Geographic Distance, Routing & Location Tool.
Calculates geographic distance, coordinates, driving time, and route estimates between locations worldwide.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the great-circle distance between two points on Earth in kilometers."""
    r = 6371.0  # Earth's radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def _compass_direction(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Calculates the compass bearing direction from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    directions = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int((bearing + 11.25) / 22.5) % 16
    return directions[idx]


def _geocode_location(location_name: str, timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    """Resolves location name to latitude and longitude using OpenStreetMap Nominatim."""
    loc_clean = location_name.strip()
    if not loc_clean:
        return None
    encoded = urllib.parse.quote(loc_clean)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=1&addressdetails=1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                item = data[0]
                return {
                    "display_name": item.get("display_name", loc_clean),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "type": item.get("type", ""),
                }
    except Exception:
        pass
    return None


def _get_osrm_route(lat1: float, lon1: float, lat2: float, lon2: float, timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    """Queries OSRM routing API for driving distance and travel duration."""
    url = f"https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
                route = data["routes"][0]
                distance_km = round(float(route["distance"]) / 1000.0, 1)
                duration_sec = float(route["duration"])
                hours = int(duration_sec // 3600)
                minutes = int((duration_sec % 3600) // 60)
                duration_str = f"{hours} Std. {minutes} Min." if hours > 0 else f"{minutes} Min."
                return {
                    "driving_distance_km": distance_km,
                    "driving_duration_seconds": int(duration_sec),
                    "driving_duration_formatted": duration_str,
                }
    except Exception:
        pass
    return None


def get_distance_route(
    origin: str = "",
    destination: str = "",
    from_place: str = "",
    to_place: str = "",
    mode: str = "driving",
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """
    Calculates geographic straight-line distance, driving route distance, coordinates, and travel time between two locations.
    """
    start_loc = (origin or from_place or "").strip()
    end_loc = (destination or to_place or "").strip()

    if not start_loc or not end_loc:
        return {"error": "Startort (origin) und Zielort (destination) müssen angegeben werden (z. B. origin='Veitshöchheim', destination='Würzburg')."}

    # Geocode origin
    geo_start = _geocode_location(start_loc, timeout=timeout / 2)
    if not geo_start:
        return {"error": f"Startort '{start_loc}' konnte nicht geokodiert werden."}

    # Geocode destination
    geo_end = _geocode_location(end_loc, timeout=timeout / 2)
    if not geo_end:
        return {"error": f"Zielort '{end_loc}' konnte nicht geokodiert werden."}

    lat1, lon1 = geo_start["lat"], geo_start["lon"]
    lat2, lon2 = geo_end["lat"], geo_end["lon"]

    straight_dist_km = round(_haversine_distance_km(lat1, lon1, lat2, lon2), 2)
    direction = _compass_direction(lat1, lon1, lat2, lon2)

    result: Dict[str, Any] = {
        "origin": {
            "name": start_loc,
            "resolved_name": geo_start["display_name"],
            "latitude": lat1,
            "longitude": lon1,
        },
        "destination": {
            "name": end_loc,
            "resolved_name": geo_end["display_name"],
            "latitude": lat2,
            "longitude": lon2,
        },
        "straight_line_distance_km": straight_dist_km,
        "direction": direction,
    }

    # Try live OSRM driving route
    osrm_data = _get_osrm_route(lat1, lon1, lat2, lon2, timeout=timeout / 2)
    if osrm_data:
        result.update(osrm_data)
        result["summary"] = (
            f"Fahrtstrecke von {start_loc} nach {end_loc}: ca. {osrm_data['driving_distance_km']} km "
            f"(Fahrzeit: {osrm_data['driving_duration_formatted']}). Luftlinie: {straight_dist_km} km Richtung {direction}."
        )
    else:
        # Fallback driving estimate: straight distance * 1.3 curve factor at 80 km/h average
        est_driving_km = round(straight_dist_km * 1.28, 1)
        est_minutes = int(est_driving_km / 80.0 * 60)
        est_hours = est_minutes // 60
        est_rem_mins = est_minutes % 60
        duration_str = f"ca. {est_hours} Std. {est_rem_mins} Min." if est_hours > 0 else f"ca. {est_minutes} Min."
        result["estimated_driving_distance_km"] = est_driving_km
        result["estimated_driving_duration"] = duration_str
        result["summary"] = (
            f"Luftlinie von {start_loc} nach {end_loc}: {straight_dist_km} km in Richtung {direction}. "
            f"Geschätzte Fahrtstrecke: ~{est_driving_km} km ({duration_str})."
        )

    return result


# Backwards-compatible alias
calculate_distance = get_distance_route
