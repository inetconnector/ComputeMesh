from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .models import EventObservation, SourceRecord, utc_now_iso
from .security import normalize_url


class ConcertStore:
    """SQLite/WAL reference store for sources, frontier, pages and events."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
        finally:
            con.close()

    def _init(self) -> None:
        with self.connection() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS cities(
              city_key TEXT PRIMARY KEY,name TEXT NOT NULL,latitude REAL,longitude REAL,timezone TEXT NOT NULL,
              first_seen TEXT NOT NULL,last_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(
              source_id INTEGER PRIMARY KEY AUTOINCREMENT,canonical_url TEXT UNIQUE NOT NULL,name TEXT NOT NULL,
              tier TEXT NOT NULL,source_type TEXT NOT NULL,city_key TEXT,priority INTEGER NOT NULL,score REAL NOT NULL,
              first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,last_crawled TEXT,next_crawl TEXT,
              consecutive_failures INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,
              etag TEXT,last_modified TEXT,content_hash TEXT,meaningful_hash TEXT,
              fetch_count INTEGER NOT NULL DEFAULT 0,change_count INTEGER NOT NULL DEFAULT 0,event_yield INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS frontier(
              url TEXT PRIMARY KEY,source_id INTEGER,city_key TEXT,depth INTEGER NOT NULL DEFAULT 0,priority REAL NOT NULL DEFAULT 0,
              discovered_from TEXT,first_seen TEXT NOT NULL,last_attempt TEXT,next_attempt TEXT,state TEXT NOT NULL DEFAULT 'queued',
              failures INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS idx_frontier_due ON frontier(state,next_attempt,priority DESC);
            CREATE TABLE IF NOT EXISTS pages(
              url TEXT PRIMARY KEY,source_id INTEGER,status_code INTEGER,fetched_at TEXT NOT NULL,content_type TEXT,
              content_hash TEXT,meaningful_hash TEXT,etag TEXT,last_modified TEXT,title TEXT,text_excerpt TEXT,
              extraction_count INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS venues(
              venue_id INTEGER PRIMARY KEY AUTOINCREMENT,canonical_name TEXT NOT NULL,city_key TEXT,latitude REAL,longitude REAL,
              address TEXT,UNIQUE(canonical_name,city_key));
            CREATE TABLE IF NOT EXISTS venue_aliases(
              venue_id INTEGER NOT NULL,alias TEXT NOT NULL,UNIQUE(venue_id,alias));
            CREATE TABLE IF NOT EXISTS events(
              event_id TEXT PRIMARY KEY,canonical_title TEXT NOT NULL,venue_id INTEGER,date_iso TEXT NOT NULL,start_time TEXT,
              end_time TEXT,price TEXT,description TEXT NOT NULL DEFAULT '',genre TEXT,artist_info TEXT,status TEXT NOT NULL,
              area TEXT,event_url TEXT,confidence REAL NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,
              last_verified TEXT NOT NULL,observation_count INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS idx_events_date ON events(date_iso);
            CREATE TABLE IF NOT EXISTS event_observations(
              observation_id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL,source_id INTEGER,observed_at TEXT NOT NULL,
              raw_json TEXT NOT NULL,fingerprint TEXT NOT NULL,extraction_method TEXT NOT NULL,confidence REAL NOT NULL,
              UNIQUE(event_id,source_id,fingerprint));
            CREATE TABLE IF NOT EXISTS event_sources(
              event_id TEXT NOT NULL,source_id INTEGER NOT NULL,event_url TEXT NOT NULL,source_name TEXT NOT NULL,last_seen TEXT NOT NULL,
              PRIMARY KEY(event_id,source_id,event_url));
            CREATE TABLE IF NOT EXISTS query_stats(
              query TEXT PRIMARY KEY,family TEXT NOT NULL,last_run TEXT,runs INTEGER NOT NULL DEFAULT 0,
              result_count INTEGER NOT NULL DEFAULT 0,new_domains INTEGER NOT NULL DEFAULT 0,new_events INTEGER NOT NULL DEFAULT 0,
              irrelevant_count INTEGER NOT NULL DEFAULT 0,score REAL NOT NULL DEFAULT 0);
            """)

    @staticmethod
    def _norm(value: str) -> str:
        text = (value or "").lower()
        for src, dst in (("ä","ae"),("ö","oe"),("ü","ue"),("ß","ss")):
            text = text.replace(src, dst)
        return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())

    @classmethod
    def city_key(cls, city: str) -> str:
        return cls._norm(city).replace(" ", "-")

    def _norm_venue(self, venue: str, city_key: str | None) -> str:
        v = self._norm(venue) or "unknown venue"
        if city_key:
            city = self._norm(city_key.replace("-", " "))
            if v.endswith(" " + city):
                v = v[:-(len(city)+1)].strip()
        return v or "unknown venue"

    def upsert_city(self, name: str, latitude: float | None = None, longitude: float | None = None, timezone_name: str = "Europe/Berlin") -> str:
        key, now = self.city_key(name), utc_now_iso()
        with self.connection() as con:
            con.execute("""INSERT INTO cities VALUES(?,?,?,?,?,?,?)
              ON CONFLICT(city_key) DO UPDATE SET name=excluded.name,latitude=COALESCE(excluded.latitude,cities.latitude),
              longitude=COALESCE(excluded.longitude,cities.longitude),timezone=excluded.timezone,last_seen=excluded.last_seen""",
              (key,name,latitude,longitude,timezone_name,now,now))
        return key

    def upsert_source(self, source: SourceRecord) -> tuple[int,bool]:
        url = normalize_url(source.url)
        if not url:
            raise ValueError("invalid source URL")
        city_key = self.upsert_city(source.city) if source.city else None
        now = utc_now_iso()
        with self.connection() as con:
            old = con.execute("SELECT source_id FROM sources WHERE canonical_url=?",(url,)).fetchone()
            con.execute("""INSERT INTO sources(canonical_url,name,tier,source_type,city_key,priority,score,first_seen,last_seen,last_crawled,next_crawl,consecutive_failures,active)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)
              ON CONFLICT(canonical_url) DO UPDATE SET name=CASE WHEN length(excluded.name)>length(sources.name) THEN excluded.name ELSE sources.name END,
              tier=CASE WHEN excluded.tier='primary' THEN 'primary' ELSE sources.tier END,
              source_type=CASE WHEN sources.source_type IN ('unknown','discovery') THEN excluded.source_type ELSE sources.source_type END,
              city_key=COALESCE(excluded.city_key,sources.city_key),priority=MIN(sources.priority,excluded.priority),
              score=MAX(sources.score,excluded.score),last_seen=excluded.last_seen,active=1""",
              (url,source.name,source.tier,source.source_type,city_key,source.priority,source.score,source.first_seen,now,
               source.last_crawled,source.next_crawl,source.consecutive_failures))
            sid = int(con.execute("SELECT source_id FROM sources WHERE canonical_url=?",(url,)).fetchone()[0])
            return sid, old is None

    def update_source_classification(self, source_id: int, *, source_type: str | None = None, tier: str | None = None,
                                     score_delta: float = 0.0, priority: int | None = None) -> None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM sources WHERE source_id=?",(source_id,)).fetchone()
            if not row:
                return
            con.execute("UPDATE sources SET source_type=?,tier=?,score=?,priority=? WHERE source_id=?",
                        (source_type or row['source_type'], tier if tier in {'primary','secondary'} else row['tier'],
                         max(-100.0,min(1000.0,float(row['score'])+score_delta)),
                         int(priority) if priority is not None else int(row['priority']), source_id))

    def record_source_failure(self, source_id: int) -> None:
        with self.connection() as con:
            con.execute("UPDATE sources SET consecutive_failures=consecutive_failures+1,score=MAX(-100,score-2) WHERE source_id=?",(source_id,))

    def enqueue(self, url: str, *, source_id: int | None = None, city_key: str | None = None, depth: int = 0,
                priority: float = 0, discovered_from: str | None = None, due: str | None = None) -> bool:
        url = normalize_url(url)
        if not url:
            return False
        now = utc_now_iso()
        with self.connection() as con:
            old = con.execute("SELECT 1 FROM frontier WHERE url=?",(url,)).fetchone()
            con.execute("""INSERT INTO frontier(url,source_id,city_key,depth,priority,discovered_from,first_seen,next_attempt,state)
              VALUES(?,?,?,?,?,?,?,?,'queued') ON CONFLICT(url) DO UPDATE SET source_id=COALESCE(excluded.source_id,frontier.source_id),
              city_key=COALESCE(excluded.city_key,frontier.city_key),depth=MIN(frontier.depth,excluded.depth),
              priority=MAX(frontier.priority,excluded.priority),state=CASE WHEN frontier.state='blocked' THEN 'blocked' ELSE 'queued' END""",
              (url,source_id,city_key,depth,priority,discovered_from,now,due or now))
            return old is None

    def due_frontier(self, limit: int) -> list[sqlite3.Row]:
        with self.connection() as con:
            return list(con.execute("""SELECT f.*,s.name source_name,s.source_type,s.tier,s.score,s.priority source_priority,s.etag,s.last_modified
              FROM frontier f LEFT JOIN sources s ON s.source_id=f.source_id WHERE f.state='queued' AND
              (f.next_attempt IS NULL OR f.next_attempt<=?) ORDER BY f.priority DESC,f.first_seen ASC LIMIT ?""",
              (utc_now_iso(),limit)))

    def mark_frontier(self, url: str, state: str, *, delay_minutes: int = 0, failure: bool = False) -> None:
        nxt = (datetime.now(timezone.utc)+timedelta(minutes=max(0,delay_minutes))).isoformat().replace("+00:00","Z")
        with self.connection() as con:
            con.execute("UPDATE frontier SET state=?,last_attempt=?,next_attempt=?,failures=failures+? WHERE url=?",
                        (state,utc_now_iso(),nxt,1 if failure else 0,normalize_url(url)))

    def source_for_url(self, url: str) -> sqlite3.Row | None:
        url = normalize_url(url)
        host = url.split('/',3)[2] if url else ''
        with self.connection() as con:
            row = con.execute("SELECT * FROM sources WHERE canonical_url=?",(url,)).fetchone()
            return row or con.execute("SELECT * FROM sources WHERE canonical_url LIKE ? ORDER BY priority LIMIT 1",(f"%://{host}/%",)).fetchone()

    def record_page(self, *, url: str, source_id: int | None, status_code: int, content_type: str, content: bytes,
                    meaningful_text: str, title: str, etag: str | None, last_modified: str | None,
                    extraction_count: int) -> tuple[bool,bool]:
        url = normalize_url(url)
        ch = hashlib.sha256(content).hexdigest()
        mh = hashlib.sha256(meaningful_text.encode('utf-8','ignore')).hexdigest()
        now = utc_now_iso()
        with self.connection() as con:
            old = con.execute("SELECT meaningful_hash FROM pages WHERE url=?",(url,)).fetchone()
            changed = old is None or old['meaningful_hash'] != mh
            con.execute("""INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(url) DO UPDATE SET source_id=excluded.source_id,status_code=excluded.status_code,fetched_at=excluded.fetched_at,
              content_type=excluded.content_type,content_hash=excluded.content_hash,meaningful_hash=excluded.meaningful_hash,
              etag=excluded.etag,last_modified=excluded.last_modified,title=excluded.title,text_excerpt=excluded.text_excerpt,
              extraction_count=excluded.extraction_count""",
              (url,source_id,status_code,now,content_type,ch,mh,etag,last_modified,title[:500],meaningful_text[:4000],extraction_count))
            if source_id:
                con.execute("""UPDATE sources SET last_crawled=?,etag=COALESCE(?,etag),last_modified=COALESCE(?,last_modified),
                  content_hash=?,meaningful_hash=?,fetch_count=fetch_count+1,change_count=change_count+?,consecutive_failures=0 WHERE source_id=?""",
                  (now,etag,last_modified,ch,mh,1 if changed else 0,source_id))
            return old is None, changed

    def _venue_id(self, con: sqlite3.Connection, venue: str, city_key: str | None, lat: float | None, lon: float | None, area: str | None) -> int:
        canonical = self._norm_venue(venue,city_key)
        row = con.execute("SELECT venue_id FROM venues WHERE canonical_name=? AND city_key IS ?",(canonical,city_key)).fetchone()
        if row:
            vid = int(row[0])
            con.execute("UPDATE venues SET latitude=COALESCE(latitude,?),longitude=COALESCE(longitude,?),address=COALESCE(address,?) WHERE venue_id=?",(lat,lon,area,vid))
        else:
            vid = int(con.execute("INSERT INTO venues(canonical_name,city_key,latitude,longitude,address) VALUES(?,?,?,?,?)",
                                  (canonical,city_key,lat,lon,area)).lastrowid)
        con.execute("INSERT OR IGNORE INTO venue_aliases(venue_id,alias) VALUES(?,?)",(vid,venue.strip()))
        return vid

    def upsert_event(self, obs: EventObservation, *, city: str | None = None, source_id: int | None = None) -> tuple[str,bool]:
        city_key = self.city_key(city) if city else None
        title_norm, venue_norm = self._norm(obs.title), self._norm_venue(obs.venue,city_key)
        raw_key = '|'.join((title_norm,venue_norm,obs.date_iso,self._norm(obs.start_time or '')))
        event_id = 'evt_'+hashlib.sha256(raw_key.encode()).hexdigest()[:24]
        fp = hashlib.sha256(json.dumps(obs.as_dict(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        now = utc_now_iso()
        with self.connection() as con:
            vid = self._venue_id(con,obs.venue,city_key,obs.venue_latitude,obs.venue_longitude,obs.area)
            existing = con.execute("SELECT * FROM events WHERE event_id=?",(event_id,)).fetchone()
            if existing is None:
                candidates = con.execute("""SELECT e.*,v.canonical_name venue_norm FROM events e JOIN venues v ON v.venue_id=e.venue_id
                  WHERE e.date_iso=? AND (e.start_time IS NULL OR ? IS NULL OR e.start_time=?) LIMIT 50""",
                  (obs.date_iso,obs.start_time,obs.start_time)).fetchall()
                best = None
                for cand in candidates:
                    ts = SequenceMatcher(None,title_norm,self._norm(cand['canonical_title'])).ratio()
                    vs = SequenceMatcher(None,venue_norm,cand['venue_norm']).ratio()
                    if ts >= .84 and vs >= .78 and (best is None or ts*.7+vs*.3 > best[0]):
                        best = (ts*.7+vs*.3,cand)
                if best:
                    event_id, existing = best[1]['event_id'], best[1]
            con.execute("""INSERT INTO events(event_id,canonical_title,venue_id,date_iso,start_time,end_time,price,description,genre,artist_info,status,area,event_url,confidence,first_seen,last_seen,last_verified,observation_count)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(event_id) DO UPDATE SET
              start_time=COALESCE(excluded.start_time,events.start_time),end_time=COALESCE(excluded.end_time,events.end_time),
              price=COALESCE(excluded.price,events.price),description=CASE WHEN length(excluded.description)>length(events.description) THEN excluded.description ELSE events.description END,
              genre=COALESCE(excluded.genre,events.genre),artist_info=COALESCE(excluded.artist_info,events.artist_info),
              status=CASE WHEN excluded.status IN ('cancelled','postponed','sold_out') THEN excluded.status ELSE events.status END,
              area=COALESCE(excluded.area,events.area),event_url=COALESCE(NULLIF(excluded.event_url,''),events.event_url),
              confidence=MAX(events.confidence,excluded.confidence),last_seen=excluded.last_seen,last_verified=excluded.last_verified,
              observation_count=events.observation_count+1""",
              (event_id,obs.title.strip(),vid,obs.date_iso,obs.start_time,obs.end_time,obs.price,obs.description,obs.genre,
               obs.artist_info,obs.status,obs.area,obs.event_url,obs.confidence,obs.observed_at,now,now))
            con.execute("""INSERT OR IGNORE INTO event_observations(event_id,source_id,observed_at,raw_json,fingerprint,extraction_method,confidence)
              VALUES(?,?,?,?,?,?,?)""",(event_id,source_id,obs.observed_at,json.dumps(obs.as_dict(),ensure_ascii=False),fp,obs.extraction_method,obs.confidence))
            if source_id:
                con.execute("""INSERT INTO event_sources VALUES(?,?,?,?,?) ON CONFLICT(event_id,source_id,event_url)
                  DO UPDATE SET last_seen=excluded.last_seen,source_name=excluded.source_name""",
                  (event_id,source_id,obs.event_url or obs.source_url,obs.source_name,now))
                con.execute("UPDATE sources SET event_yield=event_yield+? WHERE source_id=?",(1 if existing is None else 0,source_id))
            return event_id, existing is None

    def research_rows(self, city: str, date_from: str, date_to: str, max_events: int) -> list[sqlite3.Row]:
        with self.connection() as con:
            return list(con.execute("""SELECT e.*,v.latitude venue_latitude,v.longitude venue_longitude,
              COALESCE((SELECT alias FROM venue_aliases a WHERE a.venue_id=v.venue_id ORDER BY length(alias) DESC LIMIT 1),v.canonical_name) venue_name,
              (SELECT es.event_url FROM event_sources es JOIN sources s ON s.source_id=es.source_id WHERE es.event_id=e.event_id ORDER BY CASE s.tier WHEN 'primary' THEN 0 ELSE 1 END,s.priority LIMIT 1) source_url,
              (SELECT es.source_name FROM event_sources es JOIN sources s ON s.source_id=es.source_id WHERE es.event_id=e.event_id ORDER BY CASE s.tier WHEN 'primary' THEN 0 ELSE 1 END,s.priority LIMIT 1) source_name,
              (SELECT COUNT(DISTINCT source_id) FROM event_sources es WHERE es.event_id=e.event_id) corroboration_count
              FROM events e JOIN venues v ON v.venue_id=e.venue_id WHERE v.city_key=? AND e.date_iso BETWEEN ? AND ?
              ORDER BY e.date_iso,COALESCE(e.start_time,'99:99'),e.confidence DESC LIMIT ?""",
              (self.city_key(city),date_from,date_to,max_events)))

    def sources_for_city(self, city: str) -> list[sqlite3.Row]:
        with self.connection() as con:
            return list(con.execute("SELECT * FROM sources WHERE city_key=? AND active=1 ORDER BY CASE tier WHEN 'primary' THEN 0 ELSE 1 END,priority,score DESC",(self.city_key(city),)))

    def known_cities(self) -> list[sqlite3.Row]:
        with self.connection() as con:
            return list(con.execute("SELECT * FROM cities ORDER BY name"))

    def record_query_stats(self, query: str, family: str, *, results: int, new_domains: int, new_events: int, irrelevant: int = 0) -> None:
        reward = new_domains*4.0 + new_events*6.0 + min(results,10)*.2 - irrelevant*.5
        with self.connection() as con:
            con.execute("""INSERT INTO query_stats VALUES(?,?,?,1,?,?,?,?,?) ON CONFLICT(query) DO UPDATE SET last_run=excluded.last_run,
              runs=query_stats.runs+1,result_count=query_stats.result_count+excluded.result_count,new_domains=query_stats.new_domains+excluded.new_domains,
              new_events=query_stats.new_events+excluded.new_events,irrelevant_count=query_stats.irrelevant_count+excluded.irrelevant_count,
              score=query_stats.score*.8+excluded.score*.2""",(query,family,utc_now_iso(),results,new_domains,new_events,irrelevant,reward))

    def ranked_queries(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connection() as con:
            return list(con.execute("SELECT * FROM query_stats ORDER BY score DESC,last_run ASC LIMIT ?",(limit,)))
