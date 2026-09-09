# SPDX-License-Identifier: Apache-2.0
"""Current sports schedules and team metadata via TheSportsDB v1."""

from __future__ import annotations

from datetime import date as date_type
import os
import urllib.parse
from typing import Any, Dict

from .http_json import ProviderError, fetch_json

SPORTSDB_HOST = "www.thesportsdb.com"
FREE_API_KEY = "123"  # Public free v1 key documented by TheSportsDB.


def _api_key() -> str:
    return os.getenv("COMPUTEMESH_THESPORTSDB_API_KEY", FREE_API_KEY).strip() or FREE_API_KEY


def _normalize_event(item: Any) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "id": item.get("idEvent"),
        "name": item.get("strEvent") or item.get("strEventAlternate"),
        "sport": item.get("strSport"),
        "league": item.get("strLeague"),
        "league_id": item.get("idLeague"),
        "date": item.get("dateEvent"),
        "time": item.get("strTime"),
        "timestamp": item.get("strTimestamp"),
        "status": item.get("strStatus"),
        "home_team": item.get("strHomeTeam"),
        "away_team": item.get("strAwayTeam"),
        "home_score": item.get("intHomeScore"),
        "away_score": item.get("intAwayScore"),
        "venue": item.get("strVenue"),
        "country": item.get("strCountry"),
    }


def _normalize_team(item: Any) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "id": item.get("idTeam"),
        "name": item.get("strTeam"),
        "alternate_name": item.get("strTeamAlternate"),
        "sport": item.get("strSport"),
        "league": item.get("strLeague"),
        "league_id": item.get("idLeague"),
        "country": item.get("strCountry"),
        "founded": item.get("intFormedYear"),
        "stadium": item.get("strStadium"),
        "website": item.get("strWebsite"),
    }


def get_sports_data(
    query: str = "",
    mode: str = "teams",
    date: str = "",
    sport: str = "",
    league: str = "",
    league_id: str = "",
    max_results: int = 5,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Return team search or current/past/future sports schedule data.

    Modes:
      * ``teams``: search teams by name (query required)
      * ``events``: events on an ISO date (date required)
      * ``next_league`` / ``previous_league``: league schedule by numeric ID
    """
    mode_value = str(mode or "teams").strip().lower()
    if mode_value not in {"teams", "events", "next_league", "previous_league"}:
        return {"error": "mode muss teams, events, next_league oder previous_league sein."}
    try:
        limit = max(1, min(10, int(max_results)))
    except (TypeError, ValueError):
        return {"error": "max_results muss eine ganze Zahl zwischen 1 und 10 sein."}

    key = urllib.parse.quote(_api_key(), safe="")
    endpoint = ""
    params: dict[str, Any] = {}
    result_key = ""

    if mode_value == "teams":
        term = str(query or "").strip()
        if not term:
            return {"error": "query ist für mode='teams' erforderlich."}
        if len(term) > 150:
            return {"error": "query ist zu lang (maximal 150 Zeichen)."}
        endpoint = "searchteams.php"
        params = {"t": term}
        result_key = "teams"
    elif mode_value == "events":
        event_date = str(date or "").strip()
        try:
            date_type.fromisoformat(event_date)
        except ValueError:
            return {"error": "date muss im Format YYYY-MM-DD angegeben werden."}
        endpoint = "eventsday.php"
        params = {"d": event_date}
        if str(sport or "").strip():
            params["s"] = str(sport).strip()
        if str(league or "").strip():
            params["l"] = str(league).strip()
        result_key = "events"
    else:
        league_value = str(league_id or "").strip()
        if not league_value.isdigit():
            return {"error": "league_id muss für diesen Modus eine numerische TheSportsDB-League-ID sein."}
        endpoint = "eventsnextleague.php" if mode_value == "next_league" else "eventspastleague.php"
        params = {"id": league_value}
        result_key = "events"

    url = f"https://{SPORTSDB_HOST}/api/v1/json/{key}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        payload = fetch_json(url, allowed_hosts={SPORTSDB_HOST}, timeout=timeout)
    except ProviderError as exc:
        return {"error": str(exc), "provider": "TheSportsDB"}

    if not isinstance(payload, dict):
        return {"error": "TheSportsDB lieferte ein unerwartetes Antwortformat.", "provider": "TheSportsDB"}
    raw_items = payload.get(result_key)
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list):
        return {"error": "TheSportsDB lieferte eine unerwartete Ergebnisstruktur.", "provider": "TheSportsDB"}

    normalizer = _normalize_team if mode_value == "teams" else _normalize_event
    items = []
    for raw in raw_items[:limit]:
        normalized = normalizer(raw)
        if normalized is not None:
            items.append(normalized)

    return {
        "mode": mode_value,
        "query": str(query or "").strip() or None,
        "date": str(date or "").strip() or None,
        "results_count": len(items),
        "results": items,
        "source": "TheSportsDB v1",
        "live_score_note": "Die freie v1-API liefert Such- und Spielplandaten; garantierte Live-Scores sind eine Premium-Funktion.",
    }
