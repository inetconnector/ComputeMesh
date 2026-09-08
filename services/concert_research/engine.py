from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from typing import Any
from .config import ConcertResearchConfig, resolve_timezone
from .crawler import ConcertCrawler
from .fleet_ai import FleetInferenceClient
from .legacy_import import discover_default_seed_dir, import_seed_directory
from .models import ResearchRequest
from .storage import ConcertStore


class ConcertResearchEngine:
    def __init__(self, config: ConcertResearchConfig | None = None, store: ConcertStore | None = None):
        self.config=config or ConcertResearchConfig.from_env(); self.store=store or ConcertStore(self.config.db_path)
        self.ai=FleetInferenceClient(self.config); self.crawler=ConcertCrawler(self.store,self.config,self.ai)

    def bootstrap_legacy_seeds(self) -> dict[str,int]:
        seed_dir=discover_default_seed_dir()
        return import_seed_directory(seed_dir,self.crawler) if seed_dir else {"files":0,"sources":0,"created":0,"urls":0}

    def research(self, req: ResearchRequest) -> dict[str, Any]:
        tz = resolve_timezone(self.config.timezone)
        today = datetime.now(tz).date()
        start, end = req.normalized_dates(today)

        # 1. Automatic Geocoding if coordinates are not provided by client
        if req.latitude is None or req.longitude is None:
            resolved_lat, resolved_lon = self.store.resolve_city_coordinates(req.city)
            if resolved_lat is not None and resolved_lon is not None:
                req.latitude = resolved_lat
                req.longitude = resolved_lon

        # 2. Persist city in DB
        self.store.upsert_city(req.city, req.latitude, req.longitude, self.config.timezone)

        # 3. Query rows from persistent store
        rows = self.store.research_rows(
            req.city,
            start.isoformat(),
            end.isoformat(),
            req.max_events,
            latitude=req.latitude,
            longitude=req.longitude,
            radius_km=req.radius_km,
        )

        # 4. Trigger crawler refresh if force_refresh or no rows exist
        if req.force_refresh or not rows:
            self.crawler.discover(req.city, genre_terms=req.genre_terms, max_queries=16)
            self.crawler.crawl_due(
                city=req.city,
                date_from=start.isoformat(),
                date_to=end.isoformat(),
                limit=min(self.config.max_pages_per_cycle, 200),
            )
            rows = self.store.research_rows(
                req.city,
                start.isoformat(),
                end.isoformat(),
                req.max_events,
                latitude=req.latitude,
                longitude=req.longitude,
                radius_km=req.radius_km,
            )
        return self._envelope(req, today, rows)

    def daily_cycle(self, city: str, *, genre_terms: list[str] | None = None) -> dict[str, Any]:
        today = datetime.now(resolve_timezone(self.config.timezone)).date()
        discovery = self.crawler.discover(city, genre_terms=genre_terms, max_queries=24)
        crawl = self.crawler.crawl_due(city=city, date_from=today.isoformat(), date_to=(today + timedelta(days=365)).isoformat())
        return {"city": city, "discovery": discovery, "crawl": crawl}

    def _envelope(self, req: ResearchRequest, today: date, rows) -> dict[str, Any]:
        tomorrow = today + timedelta(days=1)
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            event = self._public_event(req, row)
            if event is not None:
                by_date.setdefault(row["date_iso"], []).append(event)
        sources = [
            {"name": r["name"], "url": r["canonical_url"], "tier": r["tier"] if r["tier"] in {"primary", "secondary"} else "secondary"}
            for r in self.store.sources_for_city(req.city)[:50]
        ]
        return {
            "city": req.city,
            "requestedCity": req.city,
            "notes": None,
            "today": self._day(today, "Heute", by_date.get(today.isoformat(), [])),
            "tomorrow": self._day(tomorrow, "Morgen", by_date.get(tomorrow.isoformat(), [])),
            "sources": sources,
        }

    @staticmethod
    def _day(day: date, label: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        venues = list(dict.fromkeys(e["venue"] for e in events if e["venue"]))[:10]
        genres = list(dict.fromkeys(e["genre"] for e in events if e["genre"]))[:8]
        highlights = [" · ".join(x for x in (e["startTime"], e["title"], e["venue"]) if x) for e in events[:8]]
        return {
            "dateIso": day.isoformat(),
            "dayLabel": label,
            "summary": f"{label}: {len(events)} verifizierte Konzerttreffer." if events else f"{label}: keine verifizierten Treffer.",
            "highlights": highlights,
            "venues": venues,
            "genreFocus": genres,
            "events": events,
        }

    def _public_event(self, req: ResearchRequest, row) -> dict[str, Any] | None:
        if req.latitude is not None and req.longitude is not None and req.radius_km and req.radius_km > 0:
            v_lat = row["venue_latitude"]
            v_lon = row["venue_longitude"]
            if (v_lat is None or v_lon is None) and "venue_city_key" in row.keys() and row["venue_city_key"]:
                v_city_key = row["venue_city_key"]
                req_city_key = self.store.city_key(req.city)
                if v_city_key == req_city_key:
                    v_lat, v_lon = req.latitude, req.longitude
                else:
                    c_row = self.store.get_city(v_city_key)
                    if c_row and c_row["latitude"] is not None and c_row["longitude"] is not None:
                        v_lat, v_lon = float(c_row["latitude"]), float(c_row["longitude"])

            if v_lat is not None and v_lon is not None:
                if self._distance_km(req.latitude, req.longitude, float(v_lat), float(v_lon)) > req.radius_km:
                    return None
            else:
                req_city_key = self.store.city_key(req.city)
                v_city_key = row["venue_city_key"] if "venue_city_key" in row.keys() else None
                if v_city_key and v_city_key != req_city_key:
                    return None

        source_url = row["source_url"] or row["event_url"] or ""
        source_name = row["source_name"] or "ComputeMesh Concert Index"
        why = "Verifizierter Konzerttreffer"
        corroboration = int(row["corroboration_count"] or 0)
        if corroboration >= 2:
            why += f" aus {corroboration} Quellen"
        if row["status"] != "scheduled":
            why += f"; Status: {row['status']}"
        description = row["description"] or " · ".join(
            str(x) for x in (row["canonical_title"], row["venue_name"], row["start_time"], row["price"]) if x
        )
        return {
            "title": row["canonical_title"],
            "venue": row["venue_name"],
            "area": row["area"],
            "startTime": row["start_time"],
            "endTime": row["end_time"],
            "price": row["price"],
            "description": description[:2000],
            "whyRelevant": why,
            "genre": row["genre"],
            "url": row["event_url"] or source_url,
            "sourceName": source_name,
            "sourceUrl": source_url,
            "artistInfo": row["artist_info"],
        }

    @staticmethod
    def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0088
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

