# SPDX-License-Identifier: Apache-2.0
"""Structured place/business search backed by OpenStreetMap Nominatim."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict

from .http_json import ProviderError, fetch_json

NOMINATIM_HOST = "nominatim.openstreetmap.org"


def search_places(
    query: str = "",
    location: str = "",
    limit: int = 5,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Find named places, POIs and businesses, optionally scoped to a location."""
    search_term = str(query or "").strip()
    scope = str(location or "").strip()
    if not search_term:
        return {"error": "Suchbegriff (query) darf nicht leer sein."}
    if len(search_term) > 200 or len(scope) > 200:
        return {"error": "Suchbegriff oder Ortsangabe ist zu lang (maximal 200 Zeichen)."}

    try:
        result_limit = max(1, min(10, int(limit)))
    except (TypeError, ValueError):
        return {"error": "limit muss eine ganze Zahl zwischen 1 und 10 sein."}

    combined = f"{search_term}, {scope}" if scope else search_term
    params = urllib.parse.urlencode({
        "q": combined,
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": result_limit,
    })
    url = f"https://{NOMINATIM_HOST}/search?{params}"

    try:
        payload = fetch_json(url, allowed_hosts={NOMINATIM_HOST}, timeout=timeout)
    except ProviderError as exc:
        return {"error": str(exc), "provider": "OpenStreetMap Nominatim"}

    if not isinstance(payload, list):
        return {"error": "OpenStreetMap lieferte ein unerwartetes Antwortformat.", "provider": "OpenStreetMap Nominatim"}

    results = []
    for item in payload[:result_limit]:
        if not isinstance(item, dict):
            continue
        try:
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        namedetails = item.get("namedetails") if isinstance(item.get("namedetails"), dict) else {}
        address = item.get("address") if isinstance(item.get("address"), dict) else {}
        name = (
            namedetails.get("name")
            or namedetails.get("name:de")
            or item.get("name")
            or str(item.get("display_name") or "").split(",", 1)[0]
        )
        results.append({
            "name": name,
            "display_name": item.get("display_name"),
            "category": item.get("category") or item.get("class"),
            "type": item.get("type"),
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "osm_type": item.get("osm_type"),
            "osm_id": item.get("osm_id"),
        })

    return {
        "query": search_term,
        "location": scope or None,
        "results_count": len(results),
        "results": results,
        "source": "OpenStreetMap Nominatim",
    }
