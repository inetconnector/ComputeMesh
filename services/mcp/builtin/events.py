# SPDX-License-Identifier: Apache-2.0
"""Adapter exposing the existing Event & Concert Research engine as a built-in tool."""

from __future__ import annotations

from typing import Any, Dict

from services.concert_research.engine import ConcertResearchEngine
from services.concert_research.models import ResearchRequest

_engine: ConcertResearchEngine | None = None


def _get_engine() -> ConcertResearchEngine:
    global _engine
    if _engine is None:
        _engine = ConcertResearchEngine()
    return _engine


def search_events(
    city: str = "",
    radius_km: float = 50.0,
    categories: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    query_date: str | None = None,
    day_scope: str = "today_tomorrow",
    sort: str = "recommended",
    force_refresh: bool = False,
    max_events: int = 50,
) -> Dict[str, Any]:
    """Search the existing ComputeMesh event index/crawler with category grouping."""
    target_city = str(city or "").strip()
    if not target_city:
        return {"error": "city darf nicht leer sein."}
    if len(target_city) > 160:
        return {"error": "city ist zu lang (maximal 160 Zeichen)."}
    try:
        radius = float(radius_km)
    except (TypeError, ValueError):
        return {"error": "radius_km muss eine Zahl sein."}
    if not 1 <= radius <= 300:
        return {"error": "radius_km muss zwischen 1 und 300 liegen."}
    try:
        limit = max(1, min(200, int(max_events)))
    except (TypeError, ValueError):
        return {"error": "max_events muss eine ganze Zahl zwischen 1 und 200 sein."}

    sort_value = str(sort or "recommended").strip().lower()
    if sort_value not in {"recommended", "date", "quality"}:
        return {"error": "sort muss recommended, date oder quality sein."}
    scope_value = str(day_scope or "today_tomorrow").strip().lower()
    if scope_value not in {"today", "today_tomorrow", "range"}:
        return {"error": "day_scope muss today, today_tomorrow oder range sein."}

    category_values = []
    for category in categories or []:
        value = str(category).strip()
        if value:
            category_values.append(value)

    request = ResearchRequest(
        city=target_city,
        radius_km=radius,
        categories=category_values,
        date_from=date_from,
        date_to=date_to,
        query_date=query_date,
        day_scope=scope_value,
        sort=sort_value,
        force_refresh=bool(force_refresh),
        max_events=limit,
    )
    try:
        result = _get_engine().research_events(request)
    except Exception as exc:
        return {"error": f"Event-Recherche fehlgeschlagen: {exc}"}
    if not isinstance(result, dict):
        return {"error": "Event-Recherche lieferte ein unerwartetes Antwortformat."}
    return result
