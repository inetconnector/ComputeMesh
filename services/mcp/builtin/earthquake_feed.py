# SPDX-License-Identifier: Apache-2.0
"""
USGS Real-time Global Earthquake & Seismic Activity Tool.
Provides real-time earthquake data, epicenters, depth, magnitudes, and tsunami alerts.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComputeMesh/1.2 (https://mesh.inetconnector.com)"


def get_recent_earthquakes(
    min_magnitude: float = 4.0,
    limit: int = 5,
    timeout: float = 6.0,
) -> Dict[str, Any]:
    """
    Fetches the latest significant global earthquakes from the USGS Seismic Feed in real-time.
    """
    min_mag = max(1.0, min(float(min_magnitude), 9.0))
    lim = max(1, min(int(limit), 20))

    url = f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude={min_mag}&limit={lim}&orderby=time"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        features = data.get("features", [])
        events: List[Dict[str, Any]] = []

        for f in features:
            props = f.get("properties", {})
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [0, 0, 0])  # [lon, lat, depth_km]

            epoch_ms = props.get("time", 0)
            time_str = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            events.append({
                "place": props.get("place", "Unbekannter Ort"),
                "magnitude": props.get("mag"),
                "depth_km": coords[2] if len(coords) > 2 else None,
                "latitude": coords[1] if len(coords) > 1 else None,
                "longitude": coords[0] if len(coords) > 0 else None,
                "time_utc": time_str,
                "tsunami_warning": bool(props.get("tsunami", 0)),
                "url": props.get("url", ""),
            })

        summary_lines = [f"**Aktuelle Erdbeben weltweit (ab Stärke {min_mag} M):**"]
        for ev in events[:5]:
            tsunami_str = " ⚠️ Tsunami-Warnung" if ev["tsunami_warning"] else ""
            summary_lines.append(f"- **M {ev['magnitude']}** | {ev['place']} ({ev['time_utc']}, Tiefe: {ev['depth_km']} km){tsunami_str}")

        return {
            "earthquakes_count": len(events),
            "min_magnitude": min_mag,
            "events": events,
            "summary": "\n".join(summary_lines),
            "source": "USGS Earthquake Hazards Program",
        }
    except Exception as e:
        return {"error": f"Fehler bei Abfrage des USGS-Erdbebenfeeds: {str(e)}"}


# Backwards-compatible alias
lookup_earthquakes = get_recent_earthquakes
