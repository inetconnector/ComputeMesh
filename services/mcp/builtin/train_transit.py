# SPDX-License-Identifier: Apache-2.0
"""
Public Rail & Transit Timetable Tool (Deutsche Bahn / European Rail via transport.rest & OpenStreetMap Fallback).
Retrieves real-time departures, train numbers (ICE, RE, S-Bahn), destinations, delays, platforms, and live timetable links.
Supports generic single and multi-station queries with concurrent execution.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def _split_station_queries(raw: str) -> List[str]:
    """Splits queries containing multiple stations."""
    cleaned = re.sub(r"^(?:fahrplan\s+(?:fuer|für|von|ab|in)\s+|abfahrten\s+(?:fuer|für|von|ab|in)\s+|züge\s+(?:ab|von)\s+|bahnhof\s+)", "", raw, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"[\?\.!]$", "", cleaned).strip()
    parts = re.split(r",|\s+und\s+|\s+sowie\s+|\s+and\s+|\s*\+\s*", cleaned, flags=re.IGNORECASE)
    results = []
    for p in parts:
        token = p.strip()
        if token and len(token) >= 2:
            results.append(token)
    return results if results else ([raw.strip()] if raw.strip() else [])


def _find_station_id(station_name: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
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


def _fallback_osm_station(station_name: str, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    """Fallback station resolution via OpenStreetMap Nominatim."""
    query = f"{station_name} Bahnhof" if "bahnhof" not in station_name.lower() and "hbf" not in station_name.lower() else station_name
    encoded = urllib.parse.quote(query)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded}&format=json&limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                item = data[0]
                return {
                    "name": item.get("display_name", station_name).split(",")[0],
                    "lat": float(item.get("lat", 0)),
                    "lon": float(item.get("lon", 0)),
                }
    except Exception:
        pass
    return None


def _fetch_single_station(station_query: str, max_results: int = 5, timeout: float = 6.0) -> Dict[str, Any]:
    clean_station = station_query.strip()
    st_info = _find_station_id(clean_station, timeout=min(timeout / 2, 3.0))

    if st_info and st_info.get("id"):
        st_id = st_info["id"]
        resolved_name = st_info["name"]
        lim = max(1, min(int(max_results), 10))

        url = f"https://v6.db.transport.rest/stops/{st_id}/departures?duration=120&results={lim}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=min(timeout / 2, 3.0)) as resp:
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

            if departures:
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
        except Exception:
            pass

    # Fallback to OpenStreetMap + DB Live Abfahrtstafel Portal Link
    osm_info = _fallback_osm_station(clean_station, timeout=min(timeout / 2, 3.0))
    resolved_name = osm_info["name"] if osm_info else clean_station.title()
    db_link = f"https://reiseauskunft.bahn.de/bin/bhftafel.exe/dn?input={urllib.parse.quote(clean_station)}&start=1"

    summary = (
        f"**Bahnhof {resolved_name} (Deutsche Bahn)**:\n"
        f"- **Live-Abfahrtsmonitor:** [👉 **Echtzeit-Abfahrtstafel für {resolved_name} auf bahn.de öffnen**]({db_link})\n"
        f"- **Hinweis:** Echtzeit-Abfahrten, Gleisänderungen und ICE/RE-Taktungen stehen direkt über den offiziellen DB-Abfahrtsplan zur Verfügung."
    )

    return {
        "station_name": resolved_name,
        "live_url": db_link,
        "departures_count": 0,
        "departures": [],
        "summary": summary,
        "source": "Deutsche Bahn / OpenStreetMap",
    }


def lookup_train_schedule(
    station: str = "",
    city: str = "",
    query: str = "",
    max_results: int = 5,
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Looks up live train and transit departures, destinations, platforms, and delays for any German/European train station.
    Supports single or multiple stations concurrently.
    """
    station_query = (station or city or query or "").strip()
    if not station_query:
        return {"error": "Bahnhofsname oder Stadt darf nicht leer sein (z. B. 'Würzburg Hbf', 'Frankfurt(Main)Hbf', 'München Hbf')."}

    stations = _split_station_queries(station_query)
    if len(stations) > 1:
        with ThreadPoolExecutor(max_workers=min(len(stations), 6)) as pool:
            futures = [pool.submit(_fetch_single_station, s, max_results, timeout) for s in stations]
            results = [f.result() for f in futures]
        return {
            "multiple_stations": True,
            "query": station_query,
            "stations": results,
            "source": "Deutsche Bahn / HAFAS",
        }

    return _fetch_single_station(stations[0] if stations else station_query, max_results=max_results, timeout=timeout)


# Backwards-compatible alias
lookup_trains = lookup_train_schedule
