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

    def test_automatic_geocoding_and_radius_filtering(self):
        # 1. Test automatic geocoding of Würzburg
        lat, lon = self.store.resolve_city_coordinates("Würzburg")
        self.assertIsNotNone(lat)
        self.assertIsNotNone(lon)
        self.assertAlmostEqual(lat, 49.793912, places=3)
        self.assertAlmostEqual(lon, 9.951214, places=3)

        # Verify persisted in cities table
        city_row = self.store.get_city("Würzburg")
        self.assertIsNotNone(city_row)
        self.assertAlmostEqual(float(city_row["latitude"]), 49.793912, places=3)

        # 2. Insert sources and events in different cities:
        # Würzburg (0 km), Schweinfurt (~36 km -> inside 100km), München (~220 km -> outside 100km)
        today = date.today().isoformat()
        s_wue, _ = self.store.upsert_source(SourceRecord("WueClub", "https://wue.example/events", tier="primary", city="Würzburg"))
        s_sw, _ = self.store.upsert_source(SourceRecord("SWClub", "https://sw.example/events", tier="primary", city="Schweinfurt"))
        s_muc, _ = self.store.upsert_source(SourceRecord("MUCClub", "https://muc.example/events", tier="primary", city="München"))

        self.store.resolve_city_coordinates("Schweinfurt")
        self.store.resolve_city_coordinates("München")

        # Event in Würzburg
        self.store.upsert_event(
            EventObservation("Würzburg Local Band", "B-Hof", today, "https://wue.example/events", "WueClub", "https://wue.example/1", venue_latitude=49.7939, venue_longitude=9.9512),
            city="Würzburg",
            source_id=s_wue,
        )
        # Event in Schweinfurt (~36 km from Würzburg)
        self.store.upsert_event(
            EventObservation("Schweinfurt Rock Band", "Stattbahnhof", today, "https://sw.example/events", "SWClub", "https://sw.example/2", venue_latitude=50.0454, venue_longitude=10.2334),
            city="Schweinfurt",
            source_id=s_sw,
        )
        # Event in München (~220 km from Würzburg)
        self.store.upsert_event(
            EventObservation("München Arena Concert", "Olympiahalle", today, "https://muc.example/events", "MUCClub", "https://muc.example/3", venue_latitude=48.1351, venue_longitude=11.5820),
            city="München",
            source_id=s_muc,
        )

        # Query Würzburg with radius 100 km (WITHOUT passing latitude/longitude)
        req = ResearchRequest(city="Würzburg", radius_km=100.0, date_from=today, date_to=today)
        res = self.engine.research(req)

        # Coordinates should have been automatically populated on req
        self.assertIsNotNone(req.latitude)
        self.assertIsNotNone(req.longitude)

        titles = [e["title"] for e in res["today"]["events"]]
        self.assertIn("Würzburg Local Band", titles)
        self.assertIn("Schweinfurt Rock Band", titles)
        self.assertNotIn("München Arena Concert", titles)

        # Query Würzburg with strict 20 km radius (should exclude Schweinfurt)
        req2 = ResearchRequest(city="Würzburg", radius_km=20.0, date_from=today, date_to=today)
        res2 = self.engine.research(req2)
        titles2 = [e["title"] for e in res2["today"]["events"]]
        self.assertIn("Würzburg Local Band", titles2)
        self.assertNotIn("Schweinfurt Rock Band", titles2)
        self.assertNotIn("München Arena Concert", titles2)

    def test_mcp_research_concerts_with_city_and_radius(self):
        today = date.today().isoformat()
        sid, _ = self.store.upsert_source(SourceRecord("Venue", "https://venue.example/events", tier="primary", city="Würzburg"))
        self.store.upsert_event(EventObservation("Jazz Night", "Cairo Würzburg", today, "https://venue.example/events", "Venue", "https://venue.example/jazz", start_time="20:00", venue_latitude=49.7939, venue_longitude=9.9512), city="Würzburg", source_id=sid)

        app = MCPApplication(self.engine)
        call_res = app.handle({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {
                "name": "research_concerts",
                "arguments": {
                    "city": "Würzburg",
                    "radius_km": 100,
                    "force_refresh": False,
                }
            }
        })

        self.assertIsNotNone(call_res)
        self.assertNotIn("error", call_res)
        structured = call_res["result"]["structuredContent"]
        self.assertEqual(structured["city"], "Würzburg")
        self.assertEqual(structured["requestedCity"], "Würzburg")
        self.assertIn("today", structured)
        self.assertIn("tomorrow", structured)
        self.assertEqual(len(structured["today"]["events"]), 1)
        self.assertEqual(structured["today"]["events"][0]["title"], "Jazz Night")
        self.assertEqual(structured["today"]["events"][0]["venue"], "Cairo Würzburg")

    def test_comprehensive_germany_city_geocoding(self):
        sample_cities = [
            "Berlin", "Hamburg", "München", "Köln", "Frankfurt am Main",
            "Stuttgart", "Düsseldorf", "Leipzig", "Dortmund", "Essen",
            "Bremen", "Dresden", "Hannover", "Nürnberg", "Duisburg",
            "Bochum", "Wuppertal", "Bielefeld", "Bonn", "Münster",
            "Karlsruhe", "Mannheim", "Augsburg", "Wiesbaden", "Gelsenkirchen",
            "Mönchengladbach", "Braunschweig", "Chemnitz", "Kiel", "Aachen",
            "Halle (Saale)", "Magdeburg", "Freiburg im Breisgau", "Krefeld", "Mainz",
            "Lübeck", "Erfurt", "Oberhausen", "Rostock", "Kassel",
            "Hagen", "Potsdam", "Saarbrücken", "Hamm", "Ludwigshafen am Rhein",
            "Mülheim an der Ruhr", "Oldenburg", "Osnabrück", "Leverkusen", "Heidelberg",
            "Darmstadt", "Solingen", "Herne", "Regensburg", "Paderborn",
            "Ingolstadt", "Offenbach am Main", "Fürth", "Würzburg", "Ulm",
            "Heilbronn", "Pforzheim", "Wolfsburg", "Göttingen", "Bottrop",
            "Reutlingen", "Koblenz", "Recklinghausen", "Bremerhaven", "Bergisch Gladbach",
            "Jena", "Remscheid", "Erlangen", "Moers", "Siegen",
            "Hildesheim", "Salzgitter", "Cottbus", "Kaiserslautern", "Gütersloh",
            "Schwerin", "Witten", "Gera", "Iserlohn", "Ludwigsburg",
            "Hanau", "Esslingen am Neckar", "Zwickau", "Düren", "Ratingen",
            "Tübingen", "Flensburg", "Lünen", "Villingen-Schwenningen", "Gießen",
            "Marl", "Dessau-Roßlau", "Konstanz", "Worms", "Minden",
            "Aschaffenburg", "Schweinfurt", "Bamberg", "Bayreuth", "Coburg",
            "Stralsund", "Greifswald", "Wismar", "Görlitz", "Plauen",
        ]
        for c in sample_cities:
            lat, lon = self.store.resolve_city_coordinates(c)
            self.assertIsNotNone(lat, f"Coordinates missing for {c}")
            self.assertIsNotNone(lon, f"Coordinates missing for {c}")
            self.assertGreater(lat, 47.0, f"Lat out of range for {c}: {lat}")
            self.assertLess(lat, 55.5, f"Lat out of range for {c}: {lat}")
            self.assertGreater(lon, 5.8, f"Lon out of range for {c}: {lon}")
            self.assertLess(lon, 15.5, f"Lon out of range for {c}: {lon}")

    def test_event_classification_rules_and_live_music(self):
        from services.concert_research.classifier import classify_event

        # 1. Yoga != concert (fitness_course)
        cls_yoga = classify_event("Vinyasa Yoga Flow", "Yogainsel", "Entspannender Yoga-Kurs für alle Level")
        self.assertEqual(cls_yoga.primary_category, "fitness_course")
        self.assertFalse(cls_yoga.is_live_music)

        # 2. Lauftreff != concert (fitness_course)
        cls_lauf = classify_event("Lauftreff Laufen macht Freude", "Sportzentrum Hubland", "Gemeinsames Joggen im Park")
        self.assertEqual(cls_lauf.primary_category, "fitness_course")
        self.assertFalse(cls_lauf.is_live_music)

        # 3. Party / Disko != concert (party_club)
        for party_title in [
            "Normale Donnerstagsdisko", "That escalated quickly", "Thirsty Thursday",
            "Students Night", "Mädelsabend", "Mittwochs Double", "90er Party Clubnacht"
        ]:
            cls_p = classify_event(party_title, "Kurt & Komisch", "Party mit DJ Shmurda bis in die Morgenstunden")
            self.assertEqual(cls_p.primary_category, "party_club", f"Failed for {party_title}")
            self.assertFalse(cls_p.is_live_music, f"Party should not be live music for {party_title}")

        # 4. Liveband == concert
        cls_live = classify_event("The Exploited + Support Live on Stage", "B-Hof", "Punkrock live in Würzburg", genre_hint="punk")
        self.assertEqual(cls_live.primary_category, "concert")
        self.assertTrue(cls_live.is_live_music)
        self.assertIn("punk", cls_live.genres)

        # 5. Jazz Trio == concert
        cls_jazz = classify_event("Miles Davis Tribute Jazz Trio", "Cairo", "Live Jazz Standards und Improvisation")
        self.assertEqual(cls_jazz.primary_category, "concert")
        self.assertTrue(cls_jazz.is_live_music)
        self.assertIn("jazz", cls_jazz.genres)

        # 6. Orchester == concert
        cls_orch = classify_event("Bamberger Symphoniker Orchesterkonzert", "Konzerthalle", "Klassische Sinfonie Nr. 5")
        self.assertEqual(cls_orch.primary_category, "concert")
        self.assertTrue(cls_orch.is_live_music)
        self.assertIn("classical", cls_orch.genres)

        # 7. Singer/Songwriter == concert
        cls_sing = classify_event("Acoustic Singer-Songwriter Night", "Kellerperle", "Akustik-Set mit eigenen Songs")
        self.assertEqual(cls_sing.primary_category, "concert")
        self.assertTrue(cls_sing.is_live_music)
        self.assertIn("singer_songwriter", cls_sing.genres)

        # 8. Kabarett == comedy_cabaret (with potential music secondary tag)
        cls_kab = classify_event("Kabarett: Pigor singt. Eichhorn muss begleiten.", "Disharmonie", "Musikkabarett und Chansons")
        self.assertEqual(cls_kab.primary_category, "comedy_cabaret")
        self.assertIn("concert", cls_kab.secondary_categories)
        self.assertTrue(cls_kab.is_live_music)

        # 9. Musikfestival == festival + concert tag
        cls_fest = classify_event("Würzburger Hafensommer Festival", "Mainkai", "Großes Musikfestival mit vielen Livebands")
        self.assertEqual(cls_fest.primary_category, "festival")
        self.assertIn("concert", cls_fest.secondary_categories)
        self.assertTrue(cls_fest.is_live_music)

        # 10. Weinfest mit Liveband == food_wine / festival + live music
        cls_wein = classify_event("Würzburger Weindorf mit Liveband", "Marktplatz", "Wein, Kulinarik und Livemusik")
        self.assertEqual(cls_wein.primary_category, "food_wine")
        self.assertIn("concert", cls_wein.secondary_categories)
        self.assertTrue(cls_wein.is_live_music)

        # 11. Kunstausstellung == exhibition_art
        cls_art = classify_event("Von Menschen-, Tier- & Bilderwelten", "Spitäle", "Ausstellung zeitgenössischer Malerei")
        self.assertEqual(cls_art.primary_category, "exhibition_art")
        self.assertFalse(cls_art.is_live_music)

        # 12. Politik == politics_civic
        cls_pol = classify_event("Meet & Greet Volt Würzburg", "Sternbäck", "Politisches Treffen und Kennenlernen")
        self.assertEqual(cls_pol.primary_category, "politics_civic")
        self.assertFalse(cls_pol.is_live_music)

    def test_research_concerts_filters_out_parties_and_fitness(self):
        today = date.today().isoformat()
        sid, _ = self.store.upsert_source(SourceRecord("Venue", "https://venue.example/events", tier="primary", city="Würzburg"))

        # 1. Insert Yoga
        self.store.upsert_event(EventObservation("Vinyasa Yoga Flow", "Yogainsel", today, "https://v.example/1", "Venue", "https://v.example/1", description="Yoga Kurs"), city="Würzburg", source_id=sid)
        # 2. Insert Party
        self.store.upsert_event(EventObservation("Normale Donnerstagsdisko", "Kurt & Komisch", today, "https://v.example/2", "Venue", "https://v.example/2", description="DJ Party bis 4 Uhr"), city="Würzburg", source_id=sid)
        # 3. Insert Real Concert
        self.store.upsert_event(EventObservation("The Exploited + Support Live in Concert", "B-Hof", today, "https://v.example/3", "Venue", "https://v.example/3", description="Punkband live", genre="punk"), city="Würzburg", source_id=sid)

        # Query research_concerts
        res_concerts = self.engine.research_concerts(ResearchRequest(city="Würzburg", date_from=today, date_to=today))
        titles_concerts = [e["title"] for e in res_concerts["today"]["events"]]

        self.assertIn("The Exploited + Support Live in Concert", titles_concerts)
        self.assertNotIn("Vinyasa Yoga Flow", titles_concerts)
        self.assertNotIn("Normale Donnerstagsdisko", titles_concerts)

        # Query research_events (Must contain all of them!)
        res_events = self.engine.research_events(ResearchRequest(city="Würzburg", date_from=today, date_to=today))
        titles_events = [e["title"] for e in res_events["today"]["events"]]

        self.assertIn("The Exploited + Support Live in Concert", titles_events)
        self.assertIn("Vinyasa Yoga Flow", titles_events)
        self.assertIn("Normale Donnerstagsdisko", titles_events)

        # Verify rubrized structure in research_events
        rubrics = res_events["today"]["rubrics"]
        self.assertIn("KONZERTE & LIVE-MUSIK", rubrics)
        self.assertIn("PARTY & CLUB", rubrics)
        self.assertIn("SPORT & FITNESS", rubrics)

    def test_reclassify_events_tool_and_engine(self):
        today = date.today().isoformat()
        sid, _ = self.store.upsert_source(SourceRecord("Venue", "https://venue.example/events", tier="primary", city="Würzburg"))
        self.store.upsert_event(EventObservation("Thirsty Thursday Club Party", "Das Boot", today, "https://v.example/boot", "Venue", "https://v.example/boot"), city="Würzburg", source_id=sid)

        reclass_res = self.engine.reclassify_events(100)
        self.assertGreaterEqual(reclass_res["reclassified"], 1)

        # Verify through MCP application
        app = MCPApplication(self.engine)
        call_reclass = app.handle({
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": "reclassify_events", "arguments": {"limit": 100}}
        })
        self.assertNotIn("error", call_reclass)
        self.assertIn("reclassified", call_reclass["result"]["structuredContent"])

    def test_mcp_new_tools_registration_and_calls(self):
        today = date.today().isoformat()
        sid, _ = self.store.upsert_source(SourceRecord("Venue", "https://venue.example/events", tier="primary", city="Würzburg"))
        self.store.upsert_event(EventObservation("Indie Rock Night Live", "Cairo", today, "https://v.example/cairo", "Venue", "https://v.example/cairo", genre="indie"), city="Würzburg", source_id=sid)
        self.store.upsert_event(EventObservation("Students Night", "Beerhouse", today, "https://v.example/beer", "Venue", "https://v.example/beer"), city="Würzburg", source_id=sid)

        app = MCPApplication(self.engine)
        tools_res = app.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tool_names = [t["name"] for t in tools_res["result"]["tools"]]
        self.assertIn("research_events", tool_names)
        self.assertIn("research_concerts", tool_names)
        self.assertIn("research_parties", tool_names)
        self.assertIn("research_culture", tool_names)
        self.assertIn("reclassify_events", tool_names)

        # Test research_parties
        party_call = app.handle({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "research_parties",
                "arguments": {"city": "Würzburg"}
            }
        })
        self.assertNotIn("error", party_call)
        party_events = party_call["result"]["structuredContent"]["today"]["events"]
        party_titles = [e["title"] for e in party_events]
        self.assertIn("Students Night", party_titles)
        self.assertNotIn("Indie Rock Night Live", party_titles)


if __name__=="__main__": unittest.main()


