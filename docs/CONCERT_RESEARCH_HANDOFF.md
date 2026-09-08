# Concert Research Engine engineering handoff

**Date:** 2026-09-08  
**Branch:** `feat/concert-research-engine`  
**Draft PR:** #77  
**Status:** feature branch only; not merged or deployed

## Implemented truth

The branch adds a first-party `services/concert_research/` subsystem whose purpose is to become the persistent concert-data backend for HeuteUndMorgen and other ComputeMesh consumers.

Implemented in this branch:

- SQLite/WAL persistence for cities, sources, source state, crawl frontier, pages, venues/aliases, canonical events, event observations/provenance and adaptive query statistics.
- deterministic JSON-LD/schema.org `Event`, ICS/iCalendar and RSS/Atom extraction before any LLM use;
- an identifiable robots-aware crawler with bounded response sizes, URL canonicalization, ETag/Last-Modified conditional requests, adaptive recrawl intervals and private/link-local/metadata target rejection;
- search-source discovery with configured SearXNG preferred and ordinary Google/Bing/DuckDuckGo result pages as best-effort discovery hints only;
- persistent exploration/exploitation query scoring instead of replaying a fixed query list every day;
- import of the existing `Today/HeuteUndMorgen/Data/crawler-seedlists/*.json` domain knowledge, including source priorities, URLs and `also_crawl` entries;
- deterministic/fuzzy event deduplication, venue alias normalization and multi-source corroboration;
- a `FleetInferenceClient` that sends difficult source classification, difficult event extraction and query expansion only through the configured ComputeMesh `/v1/chat/completions` gateway. Internal semantic calls set `enable_mcp=false` to avoid recursive MCP loops. No third-party LLM client is introduced;
- an index-first research engine: requests read the persistent index and trigger discovery/crawling only for bootstrap/forced refresh rather than recrawling the web for every query;
- exact outward HeuteUndMorgen canonical envelope projection (`city`, `requestedCity`, `notes`, `today`, `tomorrow`, `sources`) and exact event/source field sets;
- MCP JSON-RPC over stdio matching ComputeMesh protocol version `2026-07-28`, plus a loopback HTTP JSON-RPC surface, with `research_concerts`, `concert_refresh_city` and `concert_source_status`;
- a daily Europe/Berlin scheduler, environment example and hardened systemd service examples;
- focused tests and `docs/CONCERT_RESEARCH.md`.

## Verification in this work block

- The feature implementation's focused local test suite passed 10/10 on 2026-09-08.
- The GitHub PR runner successfully completed Python compilation for the branch.
- The first PR CI run later failed in the existing `runtime.llama.tests.test_job_attestation.JobAttestationTests.test_nodes_sign_locally_and_bundle_verifies` test because its temporary private-key file was mode `0644` while `node_key_storage.py` requires owner-only permissions.
- The current `main` SHA used as PR base (`c08a18ff24618476731dfeb4bfa84d1785f63e38`) fails at the same existing test for the same `0644` key-file reason. This failure is therefore not evidence of a Concert Research regression.
- The branch workflow adds a dedicated `Concert research tests` step before that known failing main test so feature-specific CI can be observed independently.

## Explicit boundaries

Do not claim that this branch is already globally production-proven. In particular:

- it is not merged into `main` and is not deployed;
- SQLite/WAL is the current reference persistence; large multi-worker deployment should add a transactional PostgreSQL implementation/work claiming;
- HTTP/structured-data extraction is intentionally implemented first. A browser-render adapter for genuinely JavaScript-only sources is still a production improvement, not a claimed current capability;
- the HTTP MCP mode is a bounded loopback JSON-RPC transport; stdio is the path designed to match the existing ComputeMesh MCP client. Do not describe the HTTP path as fully validated official Streamable HTTP yet;
- source discovery quality and recrawl intervals still require long-duration calibration on real city/source workloads;
- semantic quality depends on the ComputeMesh-owned inference backend actually configured behind the gateway; no third-party LLM fallback exists;
- no arbitrary provider code execution was added. Crawling remains a first-party service, while semantic inference can use the existing ComputeMesh Fleet path;
- no HeuteUndMorgen repository adapter is committed in this ComputeMesh branch. The MCP output contract was deliberately made directly consumable by the existing HeuteUndMorgen normalization/quality pipeline so that later adapter can remain small.

## Ordered next actions before merge/production deployment

1. Get the dedicated Concert Research CI step green on the current PR head and review the complete PR diff.
2. Resolve or separately merge the pre-existing `runtime.llama.tests.test_job_attestation` temp-key permission failure on `main`; do not weaken private-key permission checks to make the test pass.
3. Rebase/merge the latest `main` into the feature branch and rerun CI before making the PR non-draft.
4. Run a controlled Würzburg bootstrap from the imported HeuteUndMorgen seed pack and record source/event yield, dead sources, robots denials and false-positive rate.
5. Add source-specific/browser-render adapters only for important sources whose event data is genuinely unavailable over HTTP/feeds/structured data.
6. Add PostgreSQL + atomic distributed work claiming before horizontal crawler scaling.
7. Put authenticated operator controls in front of any HTTP MCP deployment beyond loopback.
8. Add the small `ComputeMeshMcpResearchService` adapter in HeuteUndMorgen only after the ComputeMesh data contract is accepted.
