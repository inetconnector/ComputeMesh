# SPDX-License-Identifier: Apache-2.0
"""
Public Rail & Transit Timetable Tool (Deutsche Bahn / European Rail via transport.rest).
Retrieves real-time departures, train numbers (ICE, RE, S-Bahn), destinations, delays, and platforms.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _find_station_id(station_name: str, timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    """Finds exact station EVA / UIC id using transport.rest location lookup."""
    encoded = urllib.parse.quote(station_name.strip())
    url = f"https://v6.db.transport.rest/locations?query={encoded}&results=1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                item = data[0]
                return {
                    "id": item.get("id"),
                    "name": item.get("name", station_name),
                }
    except Exception:
        pass
    return None


def lookup_train_schedule(
    station: str = "",
    city: str = "",
    query: str = "",
    max_results: int = 5,
    timeout: float = 7.0,
) -> Dict[str, Any]:
    """
    Looks up live train and transit departures, destinations, platforms, and delays for any German/European train station.
    """
    station_query = (station or city or query or "").strip()
    if not station_query:
        return {"error": "Bahnhofsname oder Stadt darf nicht leer sein (z. B. 'Würzburg Hbf', 'Frankfurt(Main)Hbf', 'München Hbf')."}

    # 1. Resolve station
    st_info = _find_station_id(station_query, timeout=timeout / 2)
    if not st_info or not st_info.get("id"):
        return {"error": f"Bahnhof '{station_query}' konnte im Fahrplansystem nicht eindeutig gefunden werden."}

    st_id = st_info["id"]
    resolved_name = st_info["name"]
    lim = max(1, min(int(max_results), 10))

    url = f"https://v6.db.transport.rest/stops/{st_id}/departures?duration=120&results={lim}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout / 2) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        departures_raw = data.get("departures", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        departures: List[Dict[str, Any]] = []

        for dep in departures_raw[:lim]:
            line_obj = dep.get("line", {})
            line_name = line_obj.get("name", "Zug")
            direction = dep.get("direction", "Unbekanntes Ziel")
            planned_when = dep.get("plannedWhen", "")[11:16] if dep.get("plannedWhen") else ""
            actual_when = dep.get("when", "")[11:16] if dep.get("when") else planned_when
            delay_mins = dep.get("delay", 0) // 60 if dep.get("delay") is not None else 0
            platform = dep.get("platform") or dep.get("plannedPlatform") or "Gleis ?"

            departures.append({
                "line": line_name,
                "direction": direction,
                "planned_time": planned_when,
                "actual_time": actual_when,
                "delay_minutes": delay_mins,
                "platform": platform,
                "cancelled": bool(dep.get("cancelled", False)),
            })

        summary_lines = [f"**Nächste Abfahrten ab {resolved_name}:**"]
        for d in departures:
            delay_str = f" (+{d['delay_minutes']} Min.)" if d["delay_minutes"] > 0 else " (Pünktlich)"
            if d["cancelled"]:
                delay_str = " (⚠️ Zug fällt aus!)"
            summary_lines.append(f"- **{d['planned_time']} Uhr** | **{d['line']}** nach {d['direction']} (Gleis {d['platform']}){delay_str}")

        return {
            "station_name": resolved_name,
            "station_id": st_id,
            "departures_count": len(departures),
            "departures": departures,
            "summary": "\n".join(summary_lines),
            "source": "Deutsche Bahn / HAFAS (transport.rest API)",
        }
    except Exception as e:
        return {"error": f"Fehler bei Fahrplan-Abfrage für '{resolved_name}': {str(e)}"}


# Backwards-compatible alias
lookup_trains = lookup_train_schedule
