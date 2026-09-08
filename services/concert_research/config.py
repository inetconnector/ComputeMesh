from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def _float(name: str, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(os.getenv(name, str(default)))))
    except ValueError:
        return default


@dataclass(frozen=True)
class ConcertResearchConfig:
    db_path: Path
    user_agent: str
    contact_url: str
    global_concurrency: int
    per_host_concurrency: int
    request_timeout_seconds: float
    max_response_bytes: int
    max_pages_per_cycle: int
    max_depth: int
    exploration_ratio: float
    freshness_hours_today: int
    freshness_hours_future: int
    search_enabled: bool
    google_enabled: bool
    bing_enabled: bool
    duckduckgo_enabled: bool
    searxng_url: str
    fleet_ai_enabled: bool
    fleet_base_url: str
    fleet_api_key: str
    fleet_model: str
    daily_hour_local: int
    timezone: str

    @classmethod
    def from_env(cls) -> "ConcertResearchConfig":
        default_db = Path(os.getenv("COMPUTEMESH_CONCERT_DB", "/var/lib/computemesh/concert_research.sqlite"))
        if os.name == "nt" and "COMPUTEMESH_CONCERT_DB" not in os.environ:
            default_db = Path.home() / ".computemesh" / "concert_research.sqlite"
        return cls(
            db_path=default_db,
            user_agent=os.getenv("COMPUTEMESH_CONCERT_USER_AGENT", "ComputeMeshConcertBot/1.0 (+https://computemesh.inetconnector.com/bot)"),
            contact_url=os.getenv("COMPUTEMESH_CONCERT_CONTACT_URL", "https://computemesh.inetconnector.com/bot"),
            global_concurrency=_int("COMPUTEMESH_CONCERT_GLOBAL_CONCURRENCY", 16, 1, 128),
            per_host_concurrency=_int("COMPUTEMESH_CONCERT_PER_HOST_CONCURRENCY", 2, 1, 16),
            request_timeout_seconds=_float("COMPUTEMESH_CONCERT_TIMEOUT_SECONDS", 15.0, 2.0, 120.0),
            max_response_bytes=_int("COMPUTEMESH_CONCERT_MAX_RESPONSE_BYTES", 2 * 1024 * 1024, 64 * 1024, 16 * 1024 * 1024),
            max_pages_per_cycle=_int("COMPUTEMESH_CONCERT_MAX_PAGES", 500, 10, 10000),
            max_depth=_int("COMPUTEMESH_CONCERT_MAX_DEPTH", 4, 0, 10),
            exploration_ratio=_float("COMPUTEMESH_CONCERT_EXPLORATION_RATIO", 0.2, 0.0, 1.0),
            freshness_hours_today=_int("COMPUTEMESH_CONCERT_FRESHNESS_TODAY_HOURS", 6, 1, 72),
            freshness_hours_future=_int("COMPUTEMESH_CONCERT_FRESHNESS_FUTURE_HOURS", 24, 1, 168),
            search_enabled=_bool("COMPUTEMESH_CONCERT_SEARCH_ENABLED", True),
            google_enabled=_bool("COMPUTEMESH_CONCERT_GOOGLE_ENABLED", True),
            bing_enabled=_bool("COMPUTEMESH_CONCERT_BING_ENABLED", True),
            duckduckgo_enabled=_bool("COMPUTEMESH_CONCERT_DDG_ENABLED", True),
            searxng_url=os.getenv("COMPUTEMESH_CONCERT_SEARXNG_URL", "").strip().rstrip("/"),
            fleet_ai_enabled=_bool("COMPUTEMESH_CONCERT_FLEET_AI_ENABLED", True),
            fleet_base_url=os.getenv("COMPUTEMESH_CONCERT_FLEET_URL", "http://127.0.0.1:8000").strip().rstrip("/"),
            fleet_api_key=os.getenv("COMPUTEMESH_CONCERT_FLEET_API_KEY", "").strip(),
            fleet_model=os.getenv("COMPUTEMESH_CONCERT_FLEET_MODEL", "qwen/qwen2.5-7b-instruct").strip(),
            daily_hour_local=_int("COMPUTEMESH_CONCERT_DAILY_HOUR", 3, 0, 23),
            timezone=os.getenv("COMPUTEMESH_CONCERT_TIMEZONE", "Europe/Berlin").strip() or "Europe/Berlin",
        )
