from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class ResearchRequest:
    city: str
    radius_km: float = 50.0
    latitude: float | None = None
    longitude: float | None = None
    postal_code: str | None = None
    city_slug: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    query_date: str | None = None
    day_scope: str = "today_tomorrow"
    categories: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    genre_profile_key: str | None = None
    genre_terms: list[str] = field(default_factory=list)
    include_adjacent_genres: bool = False
    only_live_music: bool = False
    sort: str = "recommended"  # "recommended" | "date" | "quality"
    taste_profile: str | None = None
    force_refresh: bool = False
    max_events: int = 50

    def normalized_dates(self, today: date) -> tuple[date, date]:
        def parse(value: str | None, fallback: date) -> date:
            if not value:
                return fallback
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return fallback

        if self.query_date:
            q = parse(self.query_date, today)
            return q, q
        start = parse(self.date_from, today)
        end = parse(self.date_to, today.fromordinal(today.toordinal() + 1))
        if self.day_scope == "today":
            end = start
        if end < start:
            end = start
        return start, end


@dataclass(slots=True)
class SourceRecord:
    name: str
    url: str
    tier: str = "secondary"
    source_type: str = "unknown"
    city: str | None = None
    priority: int = 50
    score: float = 0.0
    first_seen: str = field(default_factory=utc_now_iso)
    last_seen: str = field(default_factory=utc_now_iso)
    last_crawled: str | None = None
    next_crawl: str | None = None
    consecutive_failures: int = 0
    active: bool = True


@dataclass(slots=True)
class EventObservation:
    title: str
    venue: str
    date_iso: str
    source_url: str
    source_name: str
    event_url: str
    area: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    price: str | None = None
    description: str = ""
    genre: str | None = None
    artist_info: str | None = None
    status: str = "scheduled"
    venue_latitude: float | None = None
    venue_longitude: float | None = None
    extraction_method: str = "unknown"
    confidence: float = 0.5
    observed_at: str = field(default_factory=utc_now_iso)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
