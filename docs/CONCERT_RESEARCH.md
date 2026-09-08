# ComputeMesh Concert Research Engine

## Purpose

`services/concert_research/` is a persistent concert-discovery and indexing service for ComputeMesh. It replaces request-time "search everything again" workflows with a durable index that improves as sources, venues and event observations accumulate.

The semantic layer uses **ComputeMesh inference only**. It does not call third-party LLM APIs. Ordinary web/search services remain data sources.

## Data flow

```text
search / HeuteUndMorgen seeds / sitemaps / feeds / links
                    |
                    v
             persistent frontier
                    |
          safe HTTP fetch + robots
                    |
       +------------+-------------+
       |                          |
 JSON-LD / ICS / RSS          HTML snapshot
 deterministic parsers             |
       |                      difficult cases
       |                          |
       +------------> ComputeMesh Fleet AI
                    |
             event observations
                    |
        entity normalization / dedup
                    |
             persistent event index
                    |
              MCP research_concerts
                    |
                 consumers
```

## Implemented properties

- SQLite/WAL reference persistence; storage is isolated so a PostgreSQL backend can replace it later.
- Persistent source registry, page cache metadata, crawl frontier, venues, observations and query statistics.
- Conditional HTTP via ETag / Last-Modified.
- Adaptive recrawl intervals based on changes and event yield.
- robots.txt aware and identifiable `ComputeMeshConcertBot/1.0` user agent.
- SSRF protection: public HTTP(S) crawl targets only, DNS targets checked, redirects revalidated.
- Sitemap/feed/calendar discovery and bounded link-frontier expansion.
- JSON-LD `Event`, iCalendar and RSS/Atom deterministic extraction.
- Semantic source classification, difficult extraction and query expansion through the first-party ComputeMesh `/v1/chat/completions` gateway with `enable_mcp=false`.
- Search discovery via self-hosted SearXNG where configured plus best-effort ordinary Google/Bing/DuckDuckGo search frontends. Search result pages are discovery hints only; events are persisted only from fetched source content.
- Query-yield statistics with exploration/exploitation ordering.
- Fuzzy event deduplication plus venue-city alias normalization and source corroboration.
- Exact outward HeuteUndMorgen-compatible envelope.

## Environment

```text
COMPUTEMESH_CONCERT_DB=/var/lib/computemesh/concert_research.sqlite
COMPUTEMESH_CONCERT_USER_AGENT=ComputeMeshConcertBot/1.0 (+https://computemesh.inetconnector.com/bot)
COMPUTEMESH_CONCERT_GLOBAL_CONCURRENCY=16
COMPUTEMESH_CONCERT_PER_HOST_CONCURRENCY=2
COMPUTEMESH_CONCERT_MAX_PAGES=500
COMPUTEMESH_CONCERT_MAX_DEPTH=4
COMPUTEMESH_CONCERT_SEARXNG_URL=http://127.0.0.1:8080
COMPUTEMESH_CONCERT_FLEET_AI_ENABLED=true
COMPUTEMESH_CONCERT_FLEET_URL=http://127.0.0.1:8000
COMPUTEMESH_CONCERT_FLEET_API_KEY=<ComputeMesh service credential if required>
COMPUTEMESH_CONCERT_FLEET_MODEL=qwen/qwen2.5-7b-instruct
COMPUTEMESH_CONCERT_DAILY_HOUR=3
COMPUTEMESH_CONCERT_TIMEZONE=Europe/Berlin
```

`COMPUTEMESH_CONCERT_FLEET_URL` is a trusted ComputeMesh-owned inference endpoint. Do not point it at a third-party AI provider.

## Legacy HeuteUndMorgen seed import

The importer understands `Today/HeuteUndMorgen/Data/crawler-seedlists/*.json`, including source ids, `url`, `urls`, `also_crawl`, priority/type, verification state and recommended crawl order.

```bash
python -m services.concert_research.legacy_import ../Today/HeuteUndMorgen/Data/crawler-seedlists
```

If `Today` is checked out next to ComputeMesh, default path discovery can find it automatically.

## Daily indexing

One-shot:

```bash
python -m services.concert_research.scheduler --bootstrap-seeds --once
```

Long-running daily process:

```bash
python -m services.concert_research.scheduler --bootstrap-seeds
```

The scheduler runs at `COMPUTEMESH_CONCERT_DAILY_HOUR` in the configured timezone and updates every known city.

## MCP

### stdio (compatible with the existing ComputeMesh MCP client)

```bash
python -m services.concert_research.mcp_server --transport stdio --bootstrap-seeds
```

### HTTP JSON-RPC

```bash
python -m services.concert_research.mcp_server --transport http --host 127.0.0.1 --port 8098 --bootstrap-seeds
```

Endpoint: `POST /mcp`.

Tools:

- `research_concerts`
- `concert_refresh_city`
- `concert_source_status`

`research_concerts` returns `structuredContent` whose top-level fields are exactly:

```text
city, requestedCity, notes, today, tomorrow, sources
```

Each event is projected to exactly:

```text
title, venue, area, startTime, endTime, price, description,
whyRelevant, genre, url, sourceName, sourceUrl, artistInfo
```

This is the canonical `OpenAiResearchEnvelope` shape already consumed by HeuteUndMorgen, avoiding an unnecessary translation layer.

## Security boundary

Web content is always untrusted data. Fleet-AI prompts explicitly say that crawled page content is data and cannot override system rules. The crawler does not bypass CAPTCHAs, authentication or anti-bot controls and respects robots.txt.

Discovered crawl targets reject loopback, RFC1918/private, link-local, metadata and other non-public destinations before requests and after redirects. Operator-configured internal SearXNG and ComputeMesh Fleet endpoints are separate trusted configuration surfaces and are not accepted from crawled content.

No arbitrary provider code execution is introduced. Crawl execution stays a first-party service; semantic inference can use the existing ComputeMesh Fleet.

## Search strategy

The default query families include:

- city + Konzerte / Live Musik / Konzertkalender
- club and venue discovery
- cultural/youth-center discovery
- festival discovery
- configurable genre terms
- `site:` queries for known domains
- Fleet-AI generated exploratory queries for coverage gaps

Historical query yield changes ranking. Most budget is spent on proven queries, while `COMPUTEMESH_CONCERT_EXPLORATION_RATIO` reserves discovery budget for new sources.

## Source quality and freshness

Sources accumulate score from useful, changing pages and extracted events. Newly discovered sources can be semantically classified by ComputeMesh Fleet AI. High-yield event pages are recrawled more frequently; unchanged low-yield pages back off. Event observations are retained instead of overwriting provenance, allowing status/time changes and multiple-source corroboration.

## Tests

```bash
python -m unittest services.concert_research.tests.test_concert_research -v
```

The suite covers JSON-LD, ICS, exact public contract fields, MCP handshake/tool discovery, duplicate/corroboration behavior, fuzzy title + venue alias resolution, SSRF rejection, URL normalization, query-learning and the no-third-party-AI package boundary.

## Current production gates

This implementation is a strong first production-oriented reference, not a claim of complete world-wide coverage. Before very large multi-worker deployment:

1. add a PostgreSQL store implementation and transactional work claiming;
2. add optional browser-rendered source adapters for sites whose events are truly unavailable in initial HTML/feeds;
3. calibrate search/crawl budgets with real source-yield telemetry;
4. add operator auth in front of the standalone HTTP MCP route if exposed beyond loopback;
5. run long-lived physical fleet validation and crawl-load tests.

HTTP/structured-data paths deliberately remain preferred over browser rendering because they are faster, cheaper, more reproducible and less fragile.
