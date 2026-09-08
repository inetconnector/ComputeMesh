from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from services.concert_research.config import ConcertResearchConfig
from services.concert_research.engine import ConcertResearchEngine
from services.concert_research.extractors import extract_ics, extract_jsonld
from services.concert_research.mcp_server import MCPApplication, PROTOCOL_VERSION
from services.concert_research.models import EventObservation, ResearchRequest, SourceRecord
from services.concert_research.security import normalize_url, validate_public_http_url
from services.concert_research.storage import ConcertStore


class ConcertResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); base=ConcertResearchConfig.from_env()
        self.config=replace(base,db_path=Path(self.tmp.name)/"concert.sqlite",search_enabled=False,fleet_ai_enabled=False)
        self.store=ConcertStore(self.config.db_path); self.engine=ConcertResearchEngine(self.config,self.store)

    def tearDown(self): self.tmp.cleanup()

    def test_jsonld_event(self):
        block=json.dumps({"@context":"https://schema.org","@type":"MusicEvent","name":"Example Band","startDate":"2026-09-08T20:30:00+02:00","endDate":"2026-09-08T23:00:00+02:00","location":{"@type":"Place","name":"Club X","address":{"addressLocality":"Würzburg"},"geo":{"latitude":49.79,"longitude":9.94}},"offers":{"price":"18","priceCurrency":"EUR"},"url":"/events/example"})
        events=extract_jsonld([block],source_url="https://club.example/program",source_name="Club X")
        self.assertEqual(len(events),1); self.assertEqual(events[0].start_time,"20:30"); self.assertEqual(events[0].price,"18 EUR"); self.assertEqual(events[0].event_url,"https://club.example/events/example")

    def test_ics_event(self):
        ics="BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20260908T190000\nDTEND:20260908T220000\nSUMMARY:Punk Night\nLOCATION:Immerhin Würzburg\nURL:https://example.test/punk\nDESCRIPTION:Three bands live\nEND:VEVENT\nEND:VCALENDAR\n"
        events=extract_ics(ics,source_url="https://example.test/events.ics",source_name="ICS")
        self.assertEqual(len(events),1); self.assertEqual(events[0].date_iso,"2026-09-08"); self.assertEqual(events[0].start_time,"19:00")

    def test_dedup_and_corroboration(self):
        s1,_=self.store.upsert_source(SourceRecord("Venue","https://venue.example/events",tier="primary",city="Würzburg")); s2,_=self.store.upsert_source(SourceRecord("Tickets","https://tickets.example/wue",city="Würzburg"))
        a=EventObservation("Band A + Support","B-Hof Würzburg","2026-09-08","https://venue.example/events","Venue","https://venue.example/e/1",start_time="20:00",confidence=.95)
        b=EventObservation("Band A + Support","B-Hof Würzburg","2026-09-08","https://tickets.example/wue","Tickets","https://tickets.example/e/99",start_time="20:00",confidence=.8)
        id1,new1=self.store.upsert_event(a,city="Würzburg",source_id=s1); id2,new2=self.store.upsert_event(b,city="Würzburg",source_id=s2)
        self.assertEqual(id1,id2); self.assertTrue(new1); self.assertFalse(new2); self.assertEqual(self.store.research_rows("Würzburg","2026-09-08","2026-09-08",10)[0]['corroboration_count'],2)

    def test_fuzzy_title_and_venue_alias_dedup(self):
        s1,_=self.store.upsert_source(SourceRecord("Club","https://club.example/events",tier="primary",city="Würzburg")); s2,_=self.store.upsert_source(SourceRecord("Calendar","https://calendar.example/wue",city="Würzburg"))
        a=EventObservation("The Exploited + Support","B-Hof Würzburg","2026-09-09","https://club.example/events","Club","https://club.example/a",start_time="20:00")
        b=EventObservation("The Exploited + Special Support","B-Hof","2026-09-09","https://calendar.example/wue","Calendar","https://calendar.example/b",start_time="20:00")
        id1,_=self.store.upsert_event(a,city="Würzburg",source_id=s1); id2,created=self.store.upsert_event(b,city="Würzburg",source_id=s2)
        self.assertEqual(id1,id2); self.assertFalse(created)

    def test_public_contract_exact_fields(self):
        sid,_=self.store.upsert_source(SourceRecord("Venue","https://venue.example/events",tier="primary",city="Würzburg")); today=date.today().isoformat()
        self.store.upsert_event(EventObservation("Band","Club",today,"https://venue.example/events","Venue","https://venue.example/1",start_time="20:00"),city="Würzburg",source_id=sid)
        payload=self.engine.research(ResearchRequest(city="Würzburg",date_from=today,date_to=today))
        self.assertEqual(set(payload),{"city","requestedCity","notes","today","tomorrow","sources"})
        self.assertEqual(set(payload['today']['events'][0]),{"title","venue","area","startTime","endTime","price","description","whyRelevant","genre","url","sourceName","sourceUrl","artistInfo"})
        self.assertEqual(set(payload['sources'][0]),{"name","url","tier"})

    def test_mcp_initialize_and_tools(self):
        app=MCPApplication(self.engine); init=app.handle({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}); self.assertEqual(init['result']['protocolVersion'],PROTOCOL_VERSION)
        tools=app.handle({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}); self.assertIn("research_concerts",[t['name'] for t in tools['result']['tools']])

    def test_ssrf_blocks_private_targets(self):
        for target in ("http://127.0.0.1/","http://10.0.0.1/","http://169.254.169.254/latest/meta-data","file:///etc/passwd"):
            with self.assertRaises(ValueError,msg=target): validate_public_http_url(target,resolve_dns=False)

    def test_url_normalization_removes_trackers(self):
        self.assertEqual(normalize_url("https://Example.com/events/?utm_source=x&b=2&a=1#frag"),"https://example.com/events/?a=1&b=2")

    def test_no_external_ai_clients_in_package(self):
        root=Path(__file__).resolve().parents[1]
        for path in root.glob("*.py"):
            text=path.read_text(encoding="utf-8").lower()
            for forbidden in ("anthropic","gemini","perplexity"): self.assertNotIn(forbidden,text,f"{forbidden} found in {path.name}")

    def test_query_stats_learn_from_yield(self):
        self.store.record_query_stats("Würzburg Punk Konzert","genre",results=10,new_domains=2,new_events=3); self.store.record_query_stats("Würzburg foo","explore",results=10,new_domains=0,new_events=0,irrelevant=8)
        self.assertEqual(self.store.ranked_queries(10)[0]['query'],"Würzburg Punk Konzert")


if __name__=="__main__": unittest.main()
