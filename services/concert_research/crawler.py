from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import gzip
from html import unescape
import json
import random
import re
import threading
from urllib import request, error, robotparser
from urllib.parse import quote_plus, urljoin, urlsplit, unquote
import xml.etree.ElementTree as ET

from .config import ConcertResearchConfig
from .extractors import extract_feed, extract_ics, extract_jsonld, html_snapshot
from .fleet_ai import FleetInferenceClient
from .models import SourceRecord
from .security import normalize_url, validate_public_http_url
from .storage import ConcertStore


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes
    etag: str | None
    last_modified: str | None


class SafeFetcher:
    """Fetch untrusted crawl URLs with robots, SSRF, size and per-host controls."""
    def __init__(self, config: ConcertResearchConfig):
        self.config = config
        self._robots: dict[str,robotparser.RobotFileParser] = {}
        self._robots_lock = threading.Lock()
        self._host_locks: dict[str,threading.Semaphore] = {}
        self._host_locks_lock = threading.Lock()

    def _host_sem(self, host: str) -> threading.Semaphore:
        with self._host_locks_lock:
            return self._host_locks.setdefault(host,threading.Semaphore(self.config.per_host_concurrency))

    def _robot(self, url: str) -> robotparser.RobotFileParser:
        parts = urlsplit(url); base = f"{parts.scheme}://{parts.netloc}"
        with self._robots_lock:
            if base in self._robots: return self._robots[base]
        rp = robotparser.RobotFileParser(); rp.set_url(base+"/robots.txt")
        try:
            robots_url = validate_public_http_url(base+"/robots.txt")
            req = request.Request(robots_url,headers={"User-Agent":self.config.user_agent})
            with request.urlopen(req,timeout=min(8.0,self.config.request_timeout_seconds)) as resp:
                validate_public_http_url(resp.geturl())
                raw = resp.read(512*1024).decode("utf-8","replace")
            rp.parse(raw.splitlines())
        except Exception:
            rp.parse([])
        with self._robots_lock: self._robots[base] = rp
        return rp

    def allowed(self, url: str) -> bool:
        safe = validate_public_http_url(url)
        return self._robot(safe).can_fetch(self.config.user_agent,safe)

    def fetch(self, url: str, *, etag: str | None = None, last_modified: str | None = None) -> FetchResult:
        safe = validate_public_http_url(url)
        if not self.allowed(safe): raise PermissionError("robots.txt disallows crawl")
        parts = urlsplit(safe)
        headers = {"User-Agent":self.config.user_agent,"Accept":"text/html,application/xhtml+xml,application/ld+json,application/xml,text/xml,text/calendar,application/rss+xml,application/atom+xml,text/plain;q=0.8,*/*;q=0.1","Accept-Encoding":"gzip"}
        if etag: headers["If-None-Match"] = etag
        if last_modified: headers["If-Modified-Since"] = last_modified
        req = request.Request(safe,headers=headers)
        with self._host_sem(parts.hostname or ""):
            try:
                with request.urlopen(req,timeout=self.config.request_timeout_seconds) as resp:
                    final_url = validate_public_http_url(resp.geturl())
                    body = resp.read(self.config.max_response_bytes+1)
                    if len(body) > self.config.max_response_bytes: raise ValueError("response exceeds configured size limit")
                    if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                        body = gzip.decompress(body)
                        if len(body) > self.config.max_response_bytes: raise ValueError("decompressed response exceeds configured size limit")
                    return FetchResult(final_url,int(resp.status),resp.headers.get("Content-Type",""),body,resp.headers.get("ETag"),resp.headers.get("Last-Modified"))
            except error.HTTPError as exc:
                if exc.code == 304: return FetchResult(safe,304,"",b"",etag,last_modified)
                raise


class SearchDiscovery:
    """Search engines produce discovery hints, never event truth by themselves."""
    LINK = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>',re.I|re.S)

    def __init__(self, config: ConcertResearchConfig, fetcher: SafeFetcher):
        self.config,self.fetcher = config,fetcher

    def search(self, query: str, max_results: int = 10) -> list[str]:
        urls: list[str] = []
        if self.config.searxng_url:
            urls.extend(self._searx(query,max_results))
        providers: list[tuple[str,str]] = []
        if self.config.google_enabled: providers.append(("google",f"https://www.google.com/search?q={quote_plus(query)}"))
        if self.config.bing_enabled: providers.append(("bing",f"https://www.bing.com/search?q={quote_plus(query)}"))
        if self.config.duckduckgo_enabled: providers.append(("ddg",f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"))
        random.shuffle(providers)
        for name,url in providers:
            try: urls.extend(self._html_search(url))
            except Exception: continue
            if len(urls) >= max_results: break
        out: list[str] = []; seen: set[str] = set()
        for candidate in urls:
            n = normalize_url(candidate)
            if not n or n in seen: continue
            host = (urlsplit(n).hostname or "").lower()
            if any(x in host for x in ("google.","bing.com","duckduckgo.com","searx")): continue
            try: validate_public_http_url(n)
            except ValueError: continue
            seen.add(n); out.append(n)
            if len(out) >= max_results: break
        return out

    def _searx(self, query: str, max_results: int) -> list[str]:
        # Operator-configured local services are trusted configuration, unlike crawl targets.
        url = f"{self.config.searxng_url}/search?q={quote_plus(query)}&format=json&language=de-DE"
        req = request.Request(url,headers={"User-Agent":self.config.user_agent,"Accept":"application/json"})
        try:
            with request.urlopen(req,timeout=self.config.request_timeout_seconds) as resp:
                data = json.load(resp)
        except Exception:
            return []
        return [str(x.get("url")) for x in data.get("results",[]) if isinstance(x,dict) and x.get("url")][:max_results]

    def _html_search(self, url: str) -> list[str]:
        res = self.fetcher.fetch(url); html = res.body.decode("utf-8","replace"); out: list[str] = []
        for href in self.LINK.findall(html):
            href = unescape(href)
            if href.startswith("/url?"):
                m = re.search(r"[?&]q=([^&]+)",href)
                if m: href = unquote(m.group(1))
            if "uddg=" in href:
                m = re.search(r"uddg=([^&]+)",href)
                if m: href = unquote(m.group(1))
            if href.startswith("http"): out.append(href)
        return out


class ConcertCrawler:
    KEYWORDS = ("event","events","termine","veranstalt","kalender","programm","konzert","concert","live","club","gig","show","tickets","festival","musik")

    def __init__(self, store: ConcertStore, config: ConcertResearchConfig, ai: FleetInferenceClient | None = None):
        self.store,self.config = store,config
        self.fetcher = SafeFetcher(config); self.searcher = SearchDiscovery(config,self.fetcher); self.ai = ai or FleetInferenceClient(config)

    def seed_source(self, source: SourceRecord) -> tuple[int,bool]:
        sid,created = self.store.upsert_source(source); city_key = self.store.city_key(source.city) if source.city else None
        self.store.enqueue(source.url,source_id=sid,city_key=city_key,priority=max(1,100-source.priority),discovered_from="source_registry")
        base = normalize_url(source.url)
        if base:
            parts = urlsplit(base); origin = f"{parts.scheme}://{parts.netloc}"
            for path,priority in (("/sitemap.xml",90),("/feed",70),("/feed.xml",70),("/rss.xml",70),("/calendar.ics",85),("/events.ics",85)):
                self.store.enqueue(origin+path,source_id=sid,city_key=city_key,priority=priority,discovered_from=base)
        return sid,created

    def build_queries(self, city: str, genre_terms: list[str] | None = None) -> list[tuple[str,str]]:
        genres = genre_terms or ["rock","punk","hardcore","metal","indie","alternative"]
        queries = [
            (f"{city} Konzerte", "general"),
            (f"{city} Live Musik", "general"),
            (f"{city} Konzertkalender", "calendar"),
            (f"{city} Club Programm", "venue"),
            (f"{city} Kulturzentrum Konzerte", "venue"),
            (f"{city} Jugendzentrum Konzerte", "venue"),
            (f"{city} Festival Musik", "festival"),
            (f"{city} kleine Clubs Live", "venue"),
            (f"{city} Autonomes Zentrum Klapperfeld Kulturzentrum Off-Space", "subculture"),
            (f"{city} Soziokultur Kulturfabrik Freiraum Termine", "subculture"),
            (f"{city} kleine Live Bühne Jazzkeller Kellerklub Konzerte", "indie_venue"),
            (f"{city} Bürgerhaus Dorfgemeinschaftshaus Kulturscheune Kleinkunst", "community_venue"),
            (f"{city} Stadtmagazin Veranstaltungskalender Ausgehtipps", "calendar"),
        ]
        c_low = city.lower()
        if any(w in c_low for w in ("paris", "lyon", "marseille", "bordeaux", "toulouse", "lille", "nantes", "strasbourg")):
            queries.extend([
                (f"{city} friche culturelle tiers-lieux squat concerts agenda", "subculture"),
                (f"{city} café-concert club jazz musique live programmation", "venue"),
                (f"{city} salle des fêtes maison de quartier événements", "community_venue"),
            ])
        elif any(w in c_low for w in ("madrid", "barcelona", "valencia", "sevilla", "bilbao", "malaga")):
            queries.extend([
                (f"{city} centro social okupado autogestionado conciertos agenda", "subculture"),
                (f"{city} sala de conciertos pequenos directos musica club", "venue"),
                (f"{city} casa de cultura asociacion cultural eventos", "community_venue"),
            ])
        elif any(w in c_low for w in ("roma", "rome", "milano", "milan", "torino", "bologna", "napoli", "firenze")):
            queries.extend([
                (f"{city} centro sociale occupato autogestito concerti live", "subculture"),
                (f"{city} circolo arci musica dal vivo concerti club", "venue"),
                (f"{city} pro loco sagra eventi concerti", "community_venue"),
            ])
        elif any(w in c_low for w in ("london", "manchester", "bristol", "glasgow", "edinburgh", "birmingham", "new york", "los angeles", "chicago")):
            queries.extend([
                (f"{city} grassroots music venues underground DIY spaces gigs", "subculture"),
                (f"{city} basement indie gigs jazz club live sessions", "venue"),
                (f"{city} village hall community centre live music events", "community_venue"),
            ])

        queries.extend((f"{city} {g} Konzert", "genre") for g in genres[:12])
        for row in self.store.sources_for_city(city)[:20]:
            host = urlsplit(row['canonical_url']).hostname or ""
            if host: queries.append((f"site:{host} {city} Konzert Programm","known_source"))
        seen:set[str] = set(); out=[]
        for q,f in queries:
            if q.lower() not in seen: seen.add(q.lower()); out.append((q,f))
        return out

    def discover(self, city: str, *, genre_terms: list[str] | None = None, max_queries: int = 20) -> dict[str,int]:
        if not self.config.search_enabled: return {"queries":0,"new_sources":0,"results":0}
        queries = self.build_queries(city,genre_terms); ranked = {r['query']:float(r['score']) for r in self.store.ranked_queries(100)}
        queries.sort(key=lambda x: ranked.get(x[0],0),reverse=True)
        exploit = max(1,int(max_queries*(1-self.config.exploration_ratio))); selected = queries[:exploit]; extra = queries[exploit:]; random.shuffle(extra); selected += extra[:max_queries-len(selected)]
        if self.ai.available:
            selected += [(q,"ai_exploration") for q in self.ai.expand_queries(city=city,known_venues=[],genre_terms=genre_terms or [],gaps=["small venues","primary sources"])[:max(2,max_queries//4)]]
        new_sources = results_total = 0; city_key = self.store.upsert_city(city)
        for q,family in selected[:max_queries]:
            urls = self.searcher.search(q,10); results_total += len(urls); q_new = 0
            for url in urls:
                known = self.store.source_for_url(url)
                if known:
                    self.store.enqueue(url,source_id=known['source_id'],city_key=city_key,priority=40,discovered_from=f"search:{q}"); continue
                host = urlsplit(url).hostname or url
                sid,created = self.store.upsert_source(SourceRecord(name=host,url=url,tier="secondary",source_type="discovery",city=city,priority=70,score=10))
                self.store.enqueue(url,source_id=sid,city_key=city_key,priority=45,discovered_from=f"search:{q}")
                if created: new_sources += 1; q_new += 1
            self.store.record_query_stats(q,family,results=len(urls),new_domains=q_new,new_events=0)
        return {"queries":min(len(selected),max_queries),"new_sources":new_sources,"results":results_total}

    def crawl_due(self, *, city: str | None = None, date_from: str | None = None, date_to: str | None = None, limit: int | None = None) -> dict[str,int]:
        rows = self.store.due_frontier(limit or self.config.max_pages_per_cycle)
        if city:
            key = self.store.city_key(city); rows = [r for r in rows if not r['city_key'] or r['city_key']==key]
        stats = {"pages":0,"changed":0,"events":0,"new_events":0,"blocked":0,"failed":0,"new_links":0}
        with ThreadPoolExecutor(max_workers=self.config.global_concurrency) as pool:
            futures = {pool.submit(self._crawl_one,row,city=city,date_from=date_from,date_to=date_to):row for row in rows}
            for future in as_completed(futures):
                row = futures[future]
                try: result = future.result()
                except PermissionError:
                    stats['blocked'] += 1; self.store.mark_frontier(row['url'],'blocked'); continue
                except Exception:
                    stats['failed'] += 1
                    if row['source_id']: self.store.record_source_failure(int(row['source_id']))
                    self.store.mark_frontier(row['url'],'queued',delay_minutes=120,failure=True); continue
                for k,v in result.items(): stats[k] = stats.get(k,0)+v
        return stats

    def _crawl_one(self, row, *, city: str | None, date_from: str | None, date_to: str | None) -> dict[str,int]:
        result = self.fetcher.fetch(row['url'],etag=row['etag'],last_modified=row['last_modified'])
        if result.status == 304:
            self.store.mark_frontier(row['url'],'queued',delay_minutes=12*60); return {"pages":1,"changed":0,"events":0,"new_events":0,"new_links":0}
        ctype = (result.content_type or '').lower(); text = result.body.decode('utf-8','replace'); source_id = row['source_id']; source_name = row['source_name'] or (urlsplit(result.url).hostname or 'source')
        observations=[]; title=''; meaningful=''; links=[]
        if 'calendar' in ctype or result.url.lower().endswith('.ics') or 'BEGIN:VCALENDAR' in text[:500]:
            observations=extract_ics(text,source_url=result.url,source_name=source_name); meaningful=text[:20000]
        elif any(x in ctype for x in ('rss','atom')) or '<rss' in text[:500].lower() or '<feed' in text[:500].lower():
            observations=extract_feed(text,source_url=result.url,source_name=source_name); meaningful=re.sub(r'<[^>]+>',' ',text)[:20000]
        elif 'xml' in ctype or result.url.lower().endswith(('sitemap.xml','.xml')):
            meaningful=text[:20000]; links=self._xml_links(text,result.url)
        else:
            title,meaningful,links,jsonld = html_snapshot(text,result.url); observations=extract_jsonld(jsonld,source_url=result.url,source_name=source_name)
            if source_id and city and self.ai.available and row['source_type'] in (None,'unknown','discovery'):
                cls=self.ai.classify_source(url=result.url,title=title,text=meaningful,city=city)
                if cls.get('relevant'):
                    try: conf=max(0.0,min(1.0,float(cls.get('confidence',0))))
                    except (TypeError,ValueError): conf=0.0
                    self.store.update_source_classification(int(source_id),source_type=str(cls.get('source_type') or 'discovery'),tier=str(cls.get('tier') or 'secondary'),score_delta=10*conf,priority=max(5,int(row['source_priority'] or 70)-int(10*conf)))
            if city and self.ai.available and not observations and self._looks_eventish(title,meaningful):
                dfrom=date_from or datetime.now(timezone.utc).date().isoformat(); dto=date_to or (datetime.now(timezone.utc).date()+timedelta(days=30)).isoformat()
                observations += self.ai.extract_events(url=result.url,source_name=source_name,city=city,text=meaningful,date_from=dfrom,date_to=dto)
        new_links=self._enqueue_links(result.url,links,row); new_events=0
        for obs in observations:
            if date_from and obs.date_iso<date_from: continue
            if date_to and obs.date_iso>date_to: continue
            _,created=self.store.upsert_event(obs,city=city,source_id=source_id); new_events += int(created)
        _,changed=self.store.record_page(url=result.url,source_id=source_id,status_code=result.status,content_type=ctype,content=result.body,meaningful_text=meaningful,title=title,etag=result.etag,last_modified=result.last_modified,extraction_count=len(observations))
        if source_id: self.store.update_source_classification(int(source_id),score_delta=4*len(observations)+(1 if changed else -.1))
        self.store.mark_frontier(row['url'],'queued',delay_minutes=self._recrawl_minutes(changed,len(observations),result.url))
        return {"pages":1,"changed":int(changed),"events":len(observations),"new_events":new_events,"new_links":new_links}

    def _xml_links(self, text: str, base_url: str) -> list[str]:
        try: root=ET.fromstring(text)
        except ET.ParseError: return []
        return [urljoin(base_url,e.text.strip()) for e in root.iter() if e.tag.split('}')[-1].lower()=='loc' and e.text][:5000]

    def _enqueue_links(self, base_url: str, links: list[str], row) -> int:
        count=0; base_host=urlsplit(base_url).hostname or ''
        for link in links[:300]:
            n=normalize_url(link,base_url)
            if not n: continue
            try: validate_public_http_url(n)
            except ValueError: continue
            host=urlsplit(n).hostname or ''; relevant=any(k in n.lower() for k in self.KEYWORDS)
            if host!=base_host and not relevant: continue
            if row['depth']+1>self.config.max_depth: continue
            if self.store.enqueue(n,source_id=row['source_id'] if host==base_host else None,city_key=row['city_key'],depth=row['depth']+1,priority=max(5,row['priority']-5),discovered_from=base_url): count+=1
        return count

    @staticmethod
    def _looks_eventish(title: str, text: str) -> bool:
        sample=(title+' '+text[:5000]).lower()
        return any(k in sample for k in (
            'konzert', 'concert', 'live', 'veranstaltung', 'gig', 'festival', 'tickets', 'einlass', 'beginn',
            'klapperfeld', 'autonom', 'soziokultur', 'freiraum', 'off-space', 'bürgerhaus', 'scheune',
            'gemeindezentrum', 'kleinkunst', 'tiers-lieux', 'friche', 'squat', 'centro social', 'circolo',
            'grassroots', 'diy', 'soli', 'vvk', 'eintritt frei'
        ))

    @staticmethod
    def _recrawl_minutes(changed: bool, events: int, url: str) -> int:
        low=url.lower()
        if events>0: return 6*60
        if changed: return 12*60
        if any(x in low for x in ('calendar','kalender','programm','events','termine','konzert')): return 24*60
        return 72*60
