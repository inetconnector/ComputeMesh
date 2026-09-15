# SPDX-License-Identifier: Apache-2.0
"""
World Time, Calendar, Timezones & Holidays Tool.
Provides real-time datetime, global timezone conversions, calendar weeks, and statutory holidays.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    import zoneinfo
except ImportError:
    zoneinfo = None  # type: ignore

COMMON_TIMEZONE_ALIASES = {
    "berlin": "Europe/Berlin",
    "frankfurt": "Europe/Berlin",
    "munich": "Europe/Berlin",
    "münchen": "Europe/Berlin",
    "hamburg": "Europe/Berlin",
    "köln": "Europe/Berlin",
    "stuttgart": "Europe/Berlin",
    "germany": "Europe/Berlin",
    "deutschland": "Europe/Berlin",
    "vienna": "Europe/Vienna",
    "wien": "Europe/Vienna",
    "austria": "Europe/Vienna",
    "österreich": "Europe/Vienna",
    "zurich": "Europe/Zurich",
    "zürich": "Europe/Zurich",
    "switzerland": "Europe/Zurich",
    "schweiz": "Europe/Zurich",
    "london": "Europe/London",
    "uk": "Europe/London",
    "paris": "Europe/Paris",
    "frankreich": "Europe/Paris",
    "madrid": "Europe/Madrid",
    "spanien": "Europe/Madrid",
    "rom": "Europe/Rome",
    "rome": "Europe/Rome",
    "italien": "Europe/Rome",
    "warschau": "Europe/Warsaw",
    "warsaw": "Europe/Warsaw",
    "polen": "Europe/Warsaw",
    "lissabon": "Europe/Lisbon",
    "lisbon": "Europe/Lisbon",
    "athen": "Europe/Athens",
    "athens": "Europe/Athens",
    "moskau": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "istanbul": "Europe/Istanbul",
    "türkei": "Europe/Istanbul",
    "new york": "America/New_York",
    "newyork": "America/New_York",
    "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "los-angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "toronto": "America/Toronto",
    "tokyo": "Asia/Tokyo",
    "tokio": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "südkorea": "Asia/Seoul",
    "peking": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "hongkong": "Asia/Hong_Kong",
    "singapore": "Asia/Singapore",
    "singapur": "Asia/Singapore",
    "bangkok": "Asia/Bangkok",
    "thailand": "Asia/Bangkok",
    "dubai": "Asia/Dubai",
    "vae": "Asia/Dubai",
    "kairo": "Africa/Cairo",
    "cairo": "Africa/Cairo",
    "ägypten": "Africa/Cairo",
    "kapstadt": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    "johannesburg": "Africa/Johannesburg",
    "sydney": "Australia/Sydney",
    "australien": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "auckland": "Pacific/Auckland",
    "neuseeland": "Pacific/Auckland",
    "sao paulo": "America/Sao_Paulo",
    "são paulo": "America/Sao_Paulo",
    "brasilien": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "argentinien": "America/Argentina/Buenos_Aires",
    "mexiko stadt": "America/Mexico_City",
    "mexico city": "America/Mexico_City",
    "mexiko": "America/Mexico_City",
    "utc": "UTC",
    "gmt": "GMT",
}

# Fixed offsets (in hours) as robust fallback on Windows or minimal Python installations
FALLBACK_TIMEZONE_OFFSETS = {
    "Europe/Berlin": 2,  # Central European Summer Time (CEST) / Winter (CET +1)
    "Europe/Vienna": 2,
    "Europe/Zurich": 2,
    "Europe/Paris": 2,
    "Europe/Madrid": 2,
    "Europe/Rome": 2,
    "Europe/Warsaw": 2,
    "Europe/London": 1,
    "Europe/Lisbon": 1,
    "Europe/Athens": 3,
    "Europe/Moscow": 3,
    "Europe/Istanbul": 3,
    "America/New_York": -4,
    "America/Chicago": -5,
    "America/Los_Angeles": -7,
    "America/Toronto": -4,
    "America/Sao_Paulo": -3,
    "America/Argentina/Buenos_Aires": -3,
    "America/Mexico_City": -6,
    "Asia/Tokyo": 9,
    "Asia/Seoul": 9,
    "Asia/Shanghai": 8,
    "Asia/Hong_Kong": 8,
    "Asia/Singapore": 8,
    "Asia/Bangkok": 7,
    "Asia/Dubai": 4,
    "Africa/Cairo": 3,
    "Africa/Johannesburg": 2,
    "Australia/Sydney": 10,
    "Australia/Melbourne": 10,
    "Pacific/Auckland": 12,
    "UTC": 0,
    "GMT": 0,
}

GERMAN_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
GERMAN_MONTHS = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def calculate_easter_sunday(year: int) -> date:
    """Calculates Easter Sunday using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_german_holidays(year: int, state: str = "BY") -> List[Dict[str, str]]:
    """Calculates German statutory public holidays for a given year and state."""
    easter = calculate_easter_sunday(year)
    holidays = [
        {"date": f"{year}-01-01", "name": "Neujahr", "nationwide": True},
        {"date": str(easter - timedelta(days=2)), "name": "Karfreitag", "nationwide": True},
        {"date": str(easter + timedelta(days=1)), "name": "Ostermontag", "nationwide": True},
        {"date": f"{year}-05-01", "name": "Tag der Arbeit", "nationwide": True},
        {"date": str(easter + timedelta(days=39)), "name": "Christi Himmelfahrt", "nationwide": True},
        {"date": str(easter + timedelta(days=50)), "name": "Pfingstmontag", "nationwide": True},
        {"date": f"{year}-10-03", "name": "Tag der Deutschen Einheit", "nationwide": True},
        {"date": f"{year}-12-25", "name": "1. Weihnachtsfeiertag", "nationwide": True},
        {"date": f"{year}-12-26", "name": "2. Weihnachtsfeiertag", "nationwide": True},
    ]

    clean_state = (state or "BY").upper().strip()
    # State-specific holidays
    if clean_state in ("BY", "BW", "ST"):
        holidays.append({"date": f"{year}-01-06", "name": "Heilige Drei Könige", "nationwide": False})
    if clean_state in ("BY", "BW", "NW", "RP", "SL", "HE"):
        holidays.append({"date": str(easter + timedelta(days=60)), "name": "Fronleichnam", "nationwide": False})
    if clean_state in ("BY", "SL"):
        holidays.append({"date": f"{year}-08-15", "name": "Mariä Himmelfahrt", "nationwide": False})
    if clean_state in ("BY", "BW", "NW", "RP", "SL"):
        holidays.append({"date": f"{year}-11-01", "name": "Allerheiligen", "nationwide": False})

    holidays.sort(key=lambda x: x["date"])
    return holidays


def _resolve_tz(tz_name: str) -> timezone:
    """Safely resolves timezone object across Linux, Windows and minimal Python environments."""
    if zoneinfo is not None:
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except Exception:
            pass

    if tz_name in FALLBACK_TIMEZONE_OFFSETS:
        offset_hours = FALLBACK_TIMEZONE_OFFSETS[tz_name]
        return timezone(timedelta(hours=offset_hours))

    # Return local system timezone
    local_tz = datetime.now().astimezone().tzinfo
    return local_tz if local_tz is not None else timezone.utc


def _get_single_time_and_calendar(
    timezone_name: str = "",
    city: str = "",
    target_date: str = "",
    year: Optional[int] = None,
    state: str = "BY",
) -> Dict[str, Any]:
    """Internal helper to resolve a single location's time, date, and calendar metrics."""
    tz_query = (timezone_name or city or "Europe/Berlin").strip().lower()
    resolved_tz_name = COMMON_TIMEZONE_ALIASES.get(tz_query, timezone_name or "Europe/Berlin")

    tz = _resolve_tz(resolved_tz_name)
    now = datetime.now(tz)
    iso_year, iso_week, iso_day = now.isocalendar()
    weekday_de = GERMAN_WEEKDAYS[now.weekday()]
    month_de = GERMAN_MONTHS[now.month]

    current_year = year or now.year
    holidays = get_german_holidays(current_year, state=state)

    display_city = (city or timezone_name or resolved_tz_name.split("/")[-1].replace("_", " ")).strip().title()

    result: Dict[str, Any] = {
        "city": display_city,
        "datetime_iso": now.isoformat(),
        "formatted_date": f"{weekday_de}, {now.day}. {month_de} {now.year}",
        "formatted_time": now.strftime("%H:%M:%S %Z").strip(),
        "timezone": resolved_tz_name,
        "utc_offset": now.strftime("%z"),
        "calendar_week": iso_week,
        "is_leap_year": (now.year % 4 == 0 and (now.year % 100 != 0 or now.year % 400 == 0)),
        "holidays_count": len(holidays),
        "upcoming_holidays": [h for h in holidays if h["date"] >= now.strftime("%Y-%m-%d")][:4],
    }

    # If user provided a target date, calculate countdown
    if target_date:
        try:
            target_clean = target_date.strip()
            if "." in target_clean:
                parts = target_clean.split(".")
                t_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
            else:
                parts = target_clean.split("-")
                t_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            diff_days = (t_date - now.date()).days
            result["target_date"] = str(t_date)
            result["days_until_target"] = diff_days
        except Exception:
            pass

    return result


def get_time_and_calendar(
    timezone_name: str = "",
    city: str = "",
    target_date: str = "",
    year: Optional[int] = None,
    state: str = "BY",
) -> Dict[str, Any]:
    """
    Returns the current date, time, timezone conversion, calendar week, and public holidays.
    Supports multiple cities (e.g. 'New York, Tokio und Berlin').
    """
    raw_location = (timezone_name or city or "").strip()
    if not raw_location:
        return _get_single_time_and_calendar("Europe/Berlin", "Berlin", target_date, year, state)

    # Multi-location detection
    raw_cities = [c.strip().rstrip("?.!") for c in re.split(r'\s+(?:und|and|&|\+|,|sowie)\s+|,\s*', raw_location, flags=re.IGNORECASE) if c.strip()]
    cleaned_cities = [c for c in raw_cities if len(c) >= 2]

    if len(cleaned_cities) > 1:
        clocks = []
        for c_name in cleaned_cities:
            res = _get_single_time_and_calendar(city=c_name, target_date=target_date, year=year, state=state)
            clocks.append(res)
        return {
            "multiple_clocks": True,
            "clocks": clocks,
            "count": len(clocks),
        }

    return _get_single_time_and_calendar(timezone_name=timezone_name, city=city, target_date=target_date, year=year, state=state)


# Backwards-compatible alias
get_current_time = get_time_and_calendar
