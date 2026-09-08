from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import math
from typing import Any

from .classifier import RUBRIC_GROUPS
from .config import ConcertResearchConfig, resolve_timezone
from .crawler import ConcertCrawler
from .fleet_ai import FleetInferenceClient
from .legacy_import import discover_default_seed_dir, import_seed_directory
from .models import ResearchRequest
from .storage import ConcertStore


class ConcertResearchEngine:
    def __init__(self, config: ConcertResearchConfig | None = None, store: ConcertStore | None = None):
        self.config = config or ConcertResearchConfig.from_env()
        self.store = store or ConcertStore(self.config.db_path)
        self.ai = FleetInferenceClient(self.config)
        self.crawler = ConcertCrawler(self.store, self.config, self.ai)

    def bootstrap_legacy_seeds(self) -> dict[str, int]:
        seed_dir = discover_default_seed_dir()
        return import_seed_directory(seed_dir, self.crawler) if seed_dir else {"files": 0, "sources": 0, "created": 0, "urls": 0}

    def reclassify_events(self, limit: int = 50000) -> dict[str, int]:
        """Runs the multi-stage classifier across all existing events in the database."""
        count = self.store.reclassify_all_events(limit)
        return {"reclassified": count}

    def research(self, req: ResearchRequest) -> dict[str, Any]:
        """Canonical backwards-compatible entrypoint: alias for research_concerts."""
        return self.research_concerts(req)

    def research_concerts(self, req: ResearchRequest) -> dict[str, Any]:
        """Queries concerts and live music performances with genre and quality ranking."""
        tz = resolve_timezone(self.config.timezone)
        today = datetime.now(tz).date()
        start, end = req.normalized_dates(today)

        # 1. Automatic Geocoding if coordinates are omitted
        if req.latitude is None or req.longitude is None:
            resolved_lat, resolved_lon = self.store.resolve_city_coordinates(req.city)
            if resolved_lat is not None and resolved_lon is not None:
                req.latitude = resolved_lat
                req.longitude = resolved_lon

        # 2. Persist city in DB
        self.store.upsert_city(req.city, req.latitude, req.longitude, self.config.timezone)

        # 3. Query rows from persistent store (filtering strictly for concert / live music)
        rows = self.store.research_rows(
            req.city,
            start.isoformat(),
            end.isoformat(),
            req.max_events,
            latitude=req.latitude,
            longitude=req.longitude,
            radius_km=req.radius_km,
            categories=req.categories if req.categories else None,
            only_live_music=True,
            genres=req.genres if req.genres else None,
            sort=req.sort or "recommended",
        )

        # 4. Trigger crawler refresh if force_refresh or no rows exist
        if req.force_refresh or not rows:
            self.crawler.discover(req.city, genre_terms=req.genre_terms or req.genres, max_queries=16)
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
                categories=req.categories if req.categories else None,
                only_live_music=True,
                genres=req.genres if req.genres else None,
                sort=req.sort or "recommended",
            )

        return self._concert_envelope(req, today, rows)

    def research_events(self, req: ResearchRequest) -> dict[str, Any]:
        """Queries all event categories (parties, theater, exhibitions, sports, etc.) with rubrized output."""
        tz = resolve_timezone(self.config.timezone)
        today = datetime.now(tz).date()
        start, end = req.normalized_dates(today)

        if req.latitude is None or req.longitude is None:
            resolved_lat, resolved_lon = self.store.resolve_city_coordinates(req.city)
            if resolved_lat is not None and resolved_lon is not None:
                req.latitude = resolved_lat
                req.longitude = resolved_lon

        self.store.upsert_city(req.city, req.latitude, req.longitude, self.config.timezone)

        rows = self.store.research_rows(
            req.city,
            start.isoformat(),
            end.isoformat(),
            req.max_events,
            latitude=req.latitude,
            longitude=req.longitude,
            radius_km=req.radius_km,
            categories=req.categories if req.categories else None,
            only_live_music=req.only_live_music,
            genres=req.genres if req.genres else None,
            sort=req.sort or "recommended",
        )

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
                categories=req.categories if req.categories else None,
                only_live_music=req.only_live_music,
                genres=req.genres if req.genres else None,
                sort=req.sort or "recommended",
            )

        return self._events_envelope(req, today, rows)

    def daily_cycle(self, city: str, *, genre_terms: list[str] | None = None) -> dict[str, Any]:
        today = datetime.now(resolve_timezone(self.config.timezone)).date()
        discovery = self.crawler.discover(city, genre_terms=genre_terms, max_queries=24)
        crawl = self.crawler.crawl_due(city=city, date_from=today.isoformat(), date_to=(today + timedelta(days=365)).isoformat())
        return {"city": city, "discovery": discovery, "crawl": crawl}

    def _concert_envelope(self, req: ResearchRequest, today: date, rows) -> dict[str, Any]:
        tomorrow = today + timedelta(days=1)
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            event = self._public_event(req, row, extended=False)
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

    def _events_envelope(self, req: ResearchRequest, today: date, rows) -> dict[str, Any]:
        tomorrow = today + timedelta(days=1)
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            event = self._public_event(req, row, extended=True)
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
            "today": self._day_rubrized(today, "Heute", by_date.get(today.isoformat(), [])),
            "tomorrow": self._day_rubrized(tomorrow, "Morgen", by_date.get(tomorrow.isoformat(), [])),
            "sources": sources,
        }

    @staticmethod
    def _day(day: date, label: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        venues = list(dict.fromkeys(e["venue"] for e in events if e.get("venue")))[:10]
        genres = list(dict.fromkeys(e["genre"] for e in events if e.get("genre")))[:8]
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

    @classmethod
    def _day_rubrized(cls, day: date, label: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        by_rubric: dict[str, list[dict[str, Any]]] = {}
        by_category: dict[str, list[dict[str, Any]]] = {}

        for ev in events:
            cat = ev.get("primaryCategory") or "other"
            by_category.setdefault(cat, []).append(ev)

            # Assign to human-readable rubric group
            assigned_rubric = "SONSTIGES"
            for rubric_name, cat_list in RUBRIC_GROUPS.items():
                if cat in cat_list:
                    assigned_rubric = rubric_name
                    break
            by_rubric.setdefault(assigned_rubric, []).append(ev)

        # Only include populated rubrics
        active_rubrics = {k: v for k, v in by_rubric.items() if v}

        venues = list(dict.fromkeys(e["venue"] for e in events if e.get("venue")))[:10]
        highlights = [" · ".join(x for x in (e["startTime"], e["title"], e["venue"]) if x) for e in events[:8]]

        return {
            "dateIso": day.isoformat(),
            "dayLabel": label,
            "summary": f"{label}: {len(events)} verifizierte Veranstaltungen in {len(active_rubrics)} Rubriken." if events else f"{label}: keine Treffer.",
            "highlights": highlights,
            "venues": venues,
            "rubrics": active_rubrics,
            "categories": by_category,
            "events": events,
        }

    def _public_event(self, req: ResearchRequest, row, extended: bool = False) -> dict[str, Any] | None:
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
        source_name = row["source_name"] or "ComputeMesh Event Index"
        primary_cat = row["primary_category"] if "primary_category" in row.keys() else "other"
        is_live = bool(row["is_live_music"]) if "is_live_music" in row.keys() else False

        why = "Verifizierter Live-Musik-Treffer" if is_live else "Verifizierter Veranstaltungstreffer"
        corroboration = int(row["corroboration_count"] or 0)
        if corroboration >= 2:
            why += f" aus {corroboration} Quellen"
        if row["status"] != "scheduled":
            why += f"; Status: {row['status']}"

        description = row["description"] or " · ".join(
            str(x) for x in (row["canonical_title"], row["venue_name"], row["start_time"], row["price"]) if x
        )

        base_event = {
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

        if not extended:
            return base_event

        secondary_cats = []
        if "secondary_categories_json" in row.keys() and row["secondary_categories_json"]:
            try:
                secondary_cats = json.loads(row["secondary_categories_json"])
            except Exception:
                pass

        genres_list = []
        if "genres_json" in row.keys() and row["genres_json"]:
            try:
                genres_list = json.loads(row["genres_json"])
            except Exception:
                pass

        return {
            **base_event,
            "genres": genres_list,
            "primaryCategory": primary_cat,
            "secondaryCategories": secondary_cats,
            "isLiveMusic": is_live,
            "qualityScore": float(row["quality_score"]) if "quality_score" in row.keys() and row["quality_score"] is not None else 50.0,
            "recommendationScore": float(row["recommendation_score"]) if "recommendation_score" in row.keys() and row["recommendation_score"] is not None else 50.0,
        }

    @staticmethod
    def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0088
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
