"""Multi-stage Event & Genre Classification Engine for ComputeMesh.

Implements taxonomy, rule-based classification, live-music detection,
genre tagging, and quality/recommendation scoring for universal event discovery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any


PRIMARY_CATEGORIES: set[str] = {
    "concert",           # Konzerte, Livebands, Live-Musik, Tourneen, klassische Konzerte, Singer/Songwriter
    "party_club",        # Diskotheken, DJ-Nächte, Raves, Tanzpartys, Clubnächte
    "theater_stage",     # Theater, Schauspiel, Musical, Oper, Bühnenproduktionen
    "comedy_cabaret",    # Comedy, Kabarett, Satire, Stand-up
    "festival",          # Stadtfeste, Kulturfestivals, Musikfestivals, größere Mehrtagesveranstaltungen
    "exhibition_art",    # Ausstellung, Galerie, Museum, Vernissage, Kunst
    "cinema",            # Kino, Filmvorführung, Open-Air-Kino
    "lecture_reading",   # Lesung, Vortrag, Podium, wissenschaftliche Veranstaltung
    "community_social",  # Stammtisch, Meetup, gesellschaftliche Treffen, Vereinsveranstaltungen
    "politics_civic",    # Politische Treffen, Bürgerveranstaltungen, Informationsveranstaltungen
    "sports",            # Sportveranstaltung, Wettkampf, Laufveranstaltung
    "fitness_course",    # Yoga, Lauftreff, Tanzkurs, Training, Fitnesskurs
    "market_fair",       # Flohmarkt, Markt, Messe
    "food_wine",         # Weinveranstaltungen, Tastings, kulinarische Veranstaltungen
    "family_children",   # Veranstaltungen speziell für Kinder und Familien
    "tour_guided",       # Führungen, Stadtführungen, Museumsführungen
    "workshop_seminar",  # Workshop, Seminar, Kurs
    "nightlife_other",   # Abendveranstaltung, die nicht eindeutig Party oder Konzert ist
    "other",             # Fallback
}

CANONICAL_GENRES: set[str] = {
    "rock", "indie", "alternative", "pop", "singer_songwriter",
    "metal", "hardcore", "punk", "post_punk", "emo",
    "hiphop", "rap", "rnb", "soul", "funk",
    "jazz", "blues", "folk", "country", "reggae", "ska",
    "electronic_live", "experimental", "world", "latin",
    "classical", "opera", "choral", "new_music", "tribute", "cover", "other",
}

# Grouping primary categories into high-level rubrics for display
RUBRIC_GROUPS: dict[str, list[str]] = {
    "KONZERTE & LIVE-MUSIK": ["concert"],
    "PARTY & CLUB": ["party_club", "nightlife_other"],
    "THEATER & BÜHNE": ["theater_stage"],
    "COMEDY & KABARETT": ["comedy_cabaret"],
    "FESTE & FESTIVALS": ["festival"],
    "KUNST & AUSSTELLUNGEN": ["exhibition_art", "cinema"],
    "VORTRAG & LESUNG": ["lecture_reading", "politics_civic"],
    "SPORT & FITNESS": ["sports", "fitness_course"],
    "KURSE & WORKSHOPS": ["workshop_seminar", "tour_guided"],
    "GEMEINSCHAFT & KULINARIK": ["community_social", "food_wine", "market_fair", "family_children"],
    "SONSTIGES": ["other"],
}


@dataclass(slots=True)
class EventClassification:
    primary_category: str
    secondary_categories: list[str] = field(default_factory=list)
    category_confidence: float = 0.8
    is_live_music: bool = False
    live_music_confidence: float = 0.0
    genres: list[str] = field(default_factory=list)
    genre_confidence: float = 0.0
    artist_names: list[str] = field(default_factory=list)
    headliner: str | None = None
    support_acts: list[str] = field(default_factory=list)
    verification_status: str = "probable"
    verification_score: float = 0.8
    quality_score: float = 50.0
    recommendation_score: float = 50.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary_category": self.primary_category,
            "secondary_categories": self.secondary_categories,
            "category_confidence": self.category_confidence,
            "is_live_music": self.is_live_music,
            "live_music_confidence": self.live_music_confidence,
            "genres": self.genres,
            "genre_confidence": self.genre_confidence,
            "artist_names": self.artist_names,
            "headliner": self.headliner,
            "support_acts": self.support_acts,
            "verification_status": self.verification_status,
            "verification_score": self.verification_score,
            "quality_score": self.quality_score,
            "recommendation_score": self.recommendation_score,
        }


# --- REGEX & KEYWORD RULE DEFINITIONS ---

# Explicit Party/Club patterns that must NEVER be classified as pure concert
PARTY_PATTERNS = [
    re.compile(r"\b(students?\s+night|m[aä]delsabend|thirsty\s+thursday|mittwochs?\s+double|donnerstags?disko|freitags?disko|samstags?disko)\b", re.I),
    re.compile(r"\b(disco|disko|clubnacht|club\s+night|dj\s+night|dj\s+set|partyformat|tanzparty|\u00fc30|\u00fc40|afterwork|happy\s+hour)\b", re.I),
    re.compile(r"\b(that\s+escalated\s+quickly|resident\s+dj|all\s+night\s+long|keller\s+der\s+liebe|partyreihe)\b", re.I),
    re.compile(r"\b(electronic\s+beats|black\s+music\s+party|90er\s+party|2000er\s+party|apres\s+ski|clubbing)\b", re.I),
]

# Explicit Fitness & Course patterns
FITNESS_PATTERNS = [
    re.compile(r"\b(yoga|vinyasa|jivamukti|ashtanga|yin\s+yoga|hatha|pilates|qigong|meditation)\b", re.I),
    re.compile(r"\b(lauftreff|laufen\s+macht|joggen|marathon\s+training|fitnesskurs|tanzkurs|salsa\s+tanzkurs|bachata\s+kurs|hip\s*hop\s+tanzkurs|zumba)\b", re.I),
    re.compile(r"\b(workout|crossfit|rueckenschule|r\u00fcckenschule|aerobic|gymnastik)\b", re.I),
]

# Comedy & Cabaret patterns
COMEDY_PATTERNS = [
    re.compile(r"\b(kabarett|cabaret|comedy|stand-?up|satire|humor|kleinkunst|impro-?theater|poetry\s+slam|slam)\b", re.I),
]

# Theater & Stage patterns
THEATER_PATTERNS = [
    re.compile(r"\b(theater|schauspiel|b\u00fchne|oper|operette|musical|ballett|tanztheater|drama|inszenierung)\b", re.I),
]

# Exhibition & Art patterns
EXHIBITION_PATTERNS = [
    re.compile(r"\b(ausstellung|vernissage|finissage|galerie|museum|skulptur|fotografie|zeitgen\u00f6ssische\s+kunst|werkausstellung)\b", re.I),
    re.compile(r"\b(bilderwelten|malerei|exhibition|kunstsammlung)\b", re.I),
]

# Cinema patterns
CINEMA_PATTERNS = [
    re.compile(r"\b(kino|filmvorf\u00fchrung|open-?air-?kino|kinofilm|kurzfilm|sneak\s+preview|lichtspiele|filmnacht)\b", re.I),
]

# Lecture, Readings & Science
LECTURE_PATTERNS = [
    re.compile(r"\b(lesung|vortrag|autorenlesung|buchvorstellung|podiumsdiskussion|symposium|kolloquium|ringvorlesung|philosophisches\s+cafe)\b", re.I),
]

# Politics, Civic & Climate
POLITICS_PATTERNS = [
    re.compile(r"\b(partei|volt|cdu|spd|gr\u00fcne|fdp|die\s+linke|b\u00fcrgerversammlung|stadtrat|klimagespr\u00e4che|klimagespraeche|kundgebung|demo|plenum)\b", re.I),
]

# Food & Wine
FOOD_WINE_PATTERNS = [
    re.compile(r"\b(weinfest|weinparade|weindorf|weinprobe|tasting|bierprobe|craft\s+beer|oktoberfest|o\s*zapft|bierabend|weissbierdonnerstag|wei\u00dfbier|pilsmittwoch|burgertag|cocktail\s*abend|grillabend|brunch|brotzeit|schlemmen)\b", re.I),
    re.compile(r"\b(wine\s+tasting|gin\s+tasting|street\s+food|dinner|kulinarisch|kochkurs)\b", re.I),
]

# Community & Social
COMMUNITY_PATTERNS = [
    re.compile(r"\b(meet\s*&\s*greet|stammtisch|treffen|vereinstreffen|spieleabend|kickerturnier|schachturnier|reparaturchafe|repair\s+cafe)\b", re.I),
]

# Sports
SPORTS_PATTERNS = [
    re.compile(r"\b(fussball|fu\u00dfball|bundesliga|basketball|handball|volleyball|turnier|stadtlauf|marathon|triathlon|sportfest)\b", re.I),
]

# Markets & Fairs
MARKET_PATTERNS = [
    re.compile(r"\b(flohmarkt|tr\u00f6delmarkt|wochenmarkt|t\u00f6pfermarkt|handwerkermarkt|messe|kunsthandwerk)\b", re.I),
]

# Family & Children
FAMILY_PATTERNS = [
    re.compile(r"\b(kindertheater|f\u00fcr\s+kinder|familienfest|puppenb\u00fchne|puppentheater|kasperle|kinderfest|jugend)\b", re.I),
]

# Guided Tours
TOUR_PATTERNS = [
    re.compile(r"\b(stadtf\u00fchrung|museumsf\u00fchrung|rundgang|nachtw\u00e4chterf\u00fchrung|werksf\u00fchrung|architekturf\u00fchrung)\b", re.I),
]

# Workshops & Seminars
WORKSHOP_PATTERNS = [
    re.compile(r"\b(workshop|seminar|schulung|kurs|fortbildung|webinar|masterclass|hands-?on)\b", re.I),
]

# Festivals
FESTIVAL_PATTERNS = [
    re.compile(r"\b(festival|open\s*air|hafensommer|umsonst\s*&\s*drau\u00dfen|africa\s+festival|festungsflimmern|mozartfest)\b", re.I),
]

# Explicit Live-Music indicators
LIVE_MUSIC_POSITIVE_PATTERNS = [
    re.compile(r"\b(live\s+in\s+concert|live-?konzert|live-?musik|live-?band|on\s+tour|tour\s+202\d|support\s*:|special\s+guest)\b", re.I),
    re.compile(r"\b(trio|quartett|quintett|orchester|philharmonie|sinfonie|kammerorchester|ensemble|big\s+band|chor|choir)\b", re.I),
    re.compile(r"\b(singer-?songwriter|akustik-?set|unplugged|recital|solokonzert|klavierabend|orgelkonzert|band\s+live)\b", re.I),
    re.compile(r"\b(headliner|einlass\s*:\s*\d{1,2}|doors\s*:\s*\d{1,2}|vvk\s*:|ak\s*:|vorverkauf|abendkasse)\b", re.I),
]

# Genre keywords mapping
GENRE_MAP: dict[str, list[str]] = {
    "rock": ["rock", "hardrock", "classic rock", "stoner rock", "rock band", "krautrock", "grunge"],
    "indie": ["indie", "indie pop", "indie rock", "britpop", "indierock"],
    "alternative": ["alternative", "alternative rock", "alt-rock", "post-grunge"],
    "pop": ["pop", "synthpop", "electropop", "chart", "schlager"],
    "singer_songwriter": ["singer-songwriter", "singer/songwriter", "songwriter", "liedermacher", "acoustic"],
    "metal": ["metal", "heavy metal", "death metal", "black metal", "thrash metal", "power metal", "doom metal"],
    "hardcore": ["hardcore", "post-hardcore", "metalcore", "deathcore"],
    "punk": ["punk", "punkrock", "punk rock", "pop punk", "skate punk", "oi"],
    "post_punk": ["post-punk", "post punk", "dark wave", "cold wave", "goth"],
    "emo": ["emo", "screamo", "midwest emo"],
    "hiphop": ["hip-hop", "hip hop", "hiphop", "boom bap"],
    "rap": ["rap", "deutschrap", "gangsta rap", "trap"],
    "rnb": ["r&b", "rnb", "contemporary r&b"],
    "soul": ["soul", "neo soul", "motown"],
    "funk": ["funk", "groove", "afrobeat"],
    "jazz": ["jazz", "bebop", "fusion", "modern jazz", "jazz trio", "swing", "dixieland"],
    "blues": ["blues", "blues rock", "chicago blues"],
    "folk": ["folk", "folk rock", "bluegrass", "americana", "irish folk"],
    "country": ["country", "country rock", "western"],
    "reggae": ["reggae", "roots reggae", "dub", "dancehall"],
    "ska": ["ska", "ska-punk", "2-tone"],
    "electronic_live": ["electronic live", "ambient live", "modular synth live", "idm"],
    "experimental": ["experimental", "avant-garde", "noise", "improvisation"],
    "world": ["world music", "weltmusik", "klezmer", "flamenco", "bossa nova"],
    "latin": ["latin", "salsa live", "cumbia", "tango"],
    "classical": ["klassik", "klassische musik", "classical", "sinfonie", "orchester", "sonate", "kammerkonzert"],
    "opera": ["oper", "operette", "aria"],
    "choral": ["chor", "chormusik", "a cappella", "gospel"],
    "new_music": ["neue musik", "zeitgenössische musik", "contemporary classical"],
    "tribute": ["tribute", "tribute band", "tribute show"],
    "cover": ["coverband", "cover band", "covers"],
}


def classify_live_music(
    title: str,
    description: str,
    venue: str,
    artist_info: str | None = None,
    primary_category: str = "other",
) -> tuple[bool, float]:
    """Detects whether an event features an actual live-music performance."""
    text = f"{title} {description} {venue} {artist_info or ''}".lower()

    # Rule: Pure party / disco / club nights are NOT live music unless explicit live band is named
    for p in PARTY_PATTERNS:
        if p.search(title):
            # Check if explicit live band is named
            if any(k in text for k in ("live-band", "liveband", "live on stage", "konzert")):
                return (True, 0.70)
            return (False, 0.05)

    # Fitness, Yoga, Politics, Readings, Cinema, etc. are NOT live music
    if primary_category in {"fitness_course", "politics_civic", "lecture_reading", "cinema", "sports", "market_fair", "tour_guided", "workshop_seminar"}:
        return (False, 0.0)

    # Explicit positive live music cues
    pos_matches = sum(1 for p in LIVE_MUSIC_POSITIVE_PATTERNS if p.search(text))
    if pos_matches >= 2:
        return (True, 0.98)
    if pos_matches == 1:
        return (True, 0.88)

    # Specific concert keywords in title
    if any(k in title.lower() for k in ("konzert", "concert", "live", "tour", "orchester", "quartett", "trio", "recital", "band", "musikfestival", "liveband", "livebands")):
        return (True, 0.90)

    # Known live music venues
    if any(k in venue.lower() for k in ("b-hof", "posthalle", "cairo", "immerhin", "zauberberg", "keller z87", "disharmonie")):
        if not any(p.search(title) for p in PARTY_PATTERNS):
            return (True, 0.82)

    if primary_category == "concert":
        return (True, 0.85)

    if primary_category == "festival" and any(k in text for k in ("musik", "band", "live", "bühne", "konzert")):
        return (True, 0.88)

    return (False, 0.20)


def extract_genres(
    title: str,
    description: str,
    genre_hint: str | None = None,
) -> tuple[list[str], float]:
    """Extracts multiple canonical genres and overall genre confidence."""
    text = f"{title} {description} {genre_hint or ''}".lower()
    matched_genres: list[str] = []

    if genre_hint:
        hint_clean = genre_hint.strip().lower()
        if hint_clean in CANONICAL_GENRES and hint_clean not in matched_genres:
            matched_genres.append(hint_clean)

    for canonical, keywords in GENRE_MAP.items():
        if canonical in matched_genres:
            continue
        for kw in keywords:
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, text):
                matched_genres.append(canonical)
                break

    if not matched_genres:
        return ([], 0.0)

    confidence = 0.95 if genre_hint else 0.85
    return (matched_genres[:6], confidence)


def classify_event(
    title: str,
    venue: str,
    description: str = "",
    area: str | None = None,
    genre_hint: str | None = None,
    artist_info: str | None = None,
    source_type: str | None = None,
    source_name: str | None = None,
    price: str | None = None,
    url: str = "",
) -> EventClassification:
    """Performs multi-stage classification into primary category, secondary tags,

    live-music status, genres, and quality/recommendation scores.
    """
    full_text = f"{title} {description} {venue} {artist_info or ''} {source_name or ''}".lower()
    t_lower = title.strip().lower()

    primary = "other"
    secondary: list[str] = []
    confidence = 0.70

    # -------------------------------------------------------------
    # STAGE A: SOURCE HINTS & SCHEMA CUES
    # -------------------------------------------------------------
    if source_type in ("party_calendar", "club"):
        secondary.append("party_club")
    elif source_type in ("theater_calendar", "stage"):
        secondary.append("theater_stage")

    # -------------------------------------------------------------
    # STAGE B / C: DETERMINISTIC RULESETS (High Priority First)
    # -------------------------------------------------------------
    # 1. Fitness & Courses (Yoga, Lauftreff, Workout)
    if any(p.search(title) for p in FITNESS_PATTERNS):
        primary = "fitness_course"
        confidence = 0.98

    # 2. Party & Club (Students Night, Donnerstagsdisko, Mädelsabend, DJs)
    elif any(p.search(title) for p in PARTY_PATTERNS):
        primary = "party_club"
        confidence = 0.96

    # 3. Comedy & Cabaret (Kabarett, Comedy, Slam)
    elif any(p.search(title) for p in COMEDY_PATTERNS) or any(p.search(description) for p in COMEDY_PATTERNS):
        primary = "comedy_cabaret"
        confidence = 0.95
        if any(k in full_text for k in ("singt", "klavier", "musik", "lied", "chanson")):
            secondary.append("concert")

    # 4. Cinema / Movies
    elif any(p.search(title) for p in CINEMA_PATTERNS):
        primary = "cinema"
        confidence = 0.95

    # 5. Exhibition & Art
    elif any(p.search(title) for p in EXHIBITION_PATTERNS):
        primary = "exhibition_art"
        confidence = 0.94

    # 6. Politics & Civic
    elif any(p.search(title) for p in POLITICS_PATTERNS):
        primary = "politics_civic"
        confidence = 0.95

    # 7. Food, Wine & Tastings
    elif any(p.search(title) for p in FOOD_WINE_PATTERNS):
        primary = "food_wine"
        confidence = 0.92
        if any(k in full_text for k in ("liveband", "band", "live-musik", "bühne")):
            secondary.append("concert")

    # 8. Community & Meetup
    elif any(p.search(title) for p in COMMUNITY_PATTERNS):
        primary = "community_social"
        confidence = 0.90

    # 9. Theater & Stage
    elif any(p.search(title) for p in THEATER_PATTERNS):
        primary = "theater_stage"
        confidence = 0.93

    # 10. Lectures & Readings
    elif any(p.search(title) for p in LECTURE_PATTERNS):
        primary = "lecture_reading"
        confidence = 0.93

    # 11. Guided Tours
    elif any(p.search(title) for p in TOUR_PATTERNS):
        primary = "tour_guided"
        confidence = 0.92

    # 12. Markets & Fairs
    elif any(p.search(title) for p in MARKET_PATTERNS):
        primary = "market_fair"
        confidence = 0.92

    # 13. Family & Children
    elif any(p.search(title) for p in FAMILY_PATTERNS):
        primary = "family_children"
        confidence = 0.90

    # 14. Workshops
    elif any(p.search(title) for p in WORKSHOP_PATTERNS):
        primary = "workshop_seminar"
        confidence = 0.90

    # 15. Sports
    elif any(p.search(title) for p in SPORTS_PATTERNS):
        primary = "sports"
        confidence = 0.90

    # 16. Festivals
    elif any(p.search(title) for p in FESTIVAL_PATTERNS):
        primary = "festival"
        confidence = 0.94
        secondary.append("concert")

    # 17. Concerts & Live Music (Default for music acts / bands / classical)
    elif (
        any(p.search(title) for p in LIVE_MUSIC_POSITIVE_PATTERNS)
        or any(k in t_lower for k in ("konzert", "concert", "tour", "live", "band", "orchester", "sinfonie", "trio", "quartett", "recital"))
    ):
        primary = "concert"
        confidence = 0.95

    # Secondary check on description if primary is still 'other'
    if primary == "other":
        if any(p.search(description) for p in FITNESS_PATTERNS):
            primary = "fitness_course"
            confidence = 0.85
        elif any(p.search(description) for p in PARTY_PATTERNS):
            primary = "party_club"
            confidence = 0.85
        elif any(p.search(description) for p in LIVE_MUSIC_POSITIVE_PATTERNS):
            primary = "concert"
            confidence = 0.85
        elif any(p.search(description) for p in EXHIBITION_PATTERNS):
            primary = "exhibition_art"
            confidence = 0.80
        elif any(p.search(description) for p in THEATER_PATTERNS):
            primary = "theater_stage"
            confidence = 0.80

    # -------------------------------------------------------------
    # STAGE C: LIVE-MUSIC & GENRE CLASSIFICATION
    # -------------------------------------------------------------
    is_live, live_conf = classify_live_music(
        title=title,
        description=description,
        venue=venue,
        artist_info=artist_info,
        primary_category=primary,
    )

    # If live_music is strongly indicated, add concert as primary or secondary
    if is_live and primary not in ("concert", "festival", "comedy_cabaret", "theater_stage"):
        if primary == "other":
            primary = "concert"
            confidence = max(confidence, live_conf)
        elif "concert" not in secondary:
            secondary.append("concert")

    genres, genre_conf = extract_genres(
        title=title,
        description=description,
        genre_hint=genre_hint,
    )

    # Extract artist name candidates (e.g. from "Artist + Support" or "Pigor singt. Eichhorn muss begleiten")
    artists: list[str] = []
    headliner: str | None = None
    support_acts: list[str] = []

    if artist_info and artist_info.strip():
        headliner = artist_info.strip()
        artists.append(headliner)
    elif "+" in title:
        parts = [p.strip() for p in title.split("+") if p.strip()]
        if parts:
            headliner = parts[0]
            artists.append(headliner)
            support_acts = parts[1:]
            artists.extend(support_acts)
    elif ":" in title and primary in ("concert", "comedy_cabaret", "theater_stage"):
        parts = [p.strip() for p in title.split(":", 1)]
        if len(parts) == 2 and len(parts[1]) > 2:
            headliner = parts[1]
            artists.append(headliner)

    # -------------------------------------------------------------
    # STAGE D: QUALITY & RECOMMENDATION SCORING
    # -------------------------------------------------------------
    quality, recommendation = compute_quality_and_recommendation(
        primary_category=primary,
        is_live_music=is_live,
        live_music_confidence=live_conf,
        genres=genres,
        has_description=bool(description and len(description) > 30),
        has_price=bool(price),
        has_artist=bool(headliner or artists),
        venue=venue,
    )

    # Deduplicate secondary categories
    secondary_clean = [s for s in dict.fromkeys(secondary) if s != primary and s in PRIMARY_CATEGORIES]

    return EventClassification(
        primary_category=primary,
        secondary_categories=secondary_clean,
        category_confidence=round(confidence, 3),
        is_live_music=is_live,
        live_music_confidence=round(live_conf, 3),
        genres=genres,
        genre_confidence=round(genre_conf, 3),
        artist_names=artists,
        headliner=headliner,
        support_acts=support_acts,
        verification_status="verified" if confidence >= 0.9 else "probable",
        verification_score=round(confidence, 3),
        quality_score=round(quality, 1),
        recommendation_score=round(recommendation, 1),
    )


def compute_quality_and_recommendation(
    primary_category: str,
    is_live_music: bool,
    live_music_confidence: float,
    genres: list[str],
    has_description: bool,
    has_price: bool,
    has_artist: bool,
    venue: str,
) -> tuple[float, float]:
    """Calculates quality_score (informational completeness & trustworthiness)

    and recommendation_score (interestingness & relevance for users).
    """
    quality = 50.0
    if has_description:
        quality += 15.0
    if has_price:
        quality += 10.0
    if has_artist:
        quality += 15.0
    if venue and venue.lower() != "unknown venue":
        quality += 10.0
    quality = max(10.0, min(100.0, quality))

    # Recommendation scoring
    rec = 50.0
    if is_live_music:
        rec += 20.0 * live_music_confidence
    if genres:
        rec += min(15.0, len(genres) * 5.0)
    if has_artist:
        rec += 10.0
    if primary_category in ("concert", "festival", "comedy_cabaret"):
        rec += 10.0
    elif primary_category in ("fitness_course", "community_social"):
        rec -= 10.0

    rec = max(10.0, min(100.0, rec))
    return quality, rec
