# ComputeMesh MCP and Live Tool Engine

ComputeMesh exposes built-in live-data tools through `ToolRegistry` and can also attach explicitly configured external MCP stdio servers through `MCPClient`.

## Built-in tool surface

With the normal configuration (`system_tools_enabled=false`) the registry exposes 25 built-in tools. Enabling the owner-only system information tool raises the total to 26.

| Area | Tools |
| --- | --- |
| Web/current information | `search_web`, `fetch_web_content`, `get_live_news` |
| Weather | `get_current_weather`, `get_weather_forecast` |
| Local discovery | `search_events`, `search_places`, `get_distance_route` |
| Markets/business | `get_market_quote`, `convert_currency`, `lookup_company` |
| Sports/transit | `get_sports_data`, `lookup_train_schedule` |
| Reference/open data | `get_wikipedia_summary`, `lookup_country_data`, `get_world_bank_stats`, `search_arxiv_papers`, `lookup_food_product`, `lookup_software_package`, `get_recent_earthquakes`, `lookup_chemical_compound`, `lookup_word_definition` |
| Calculation/time | `calculate_math`, `get_time_and_calendar` |
| Owner-only diagnostics | `lookup_network_host`, optionally `get_system_info` |

`search_events` reuses the existing `services.concert_research` index/crawler rather than maintaining a second event database. Public registry calls do not expose the operator-only `force_refresh` control.

### Live data providers added by the completion audit

- Weather forecast: Open-Meteo.
- Places/POIs: OpenStreetMap Nominatim.
- Sports schedules/team data: TheSportsDB v1. The built-in tool does not claim premium guaranteed live-score coverage.
- Company/legal-entity data: GLEIF Global LEI Index. No LEI result is not proof that a company does not exist.
- Events: the existing ComputeMesh Event & Concert Research engine.

No provider secret is hard-coded. TheSportsDB's documented public v1 key is used by default and may be replaced with `COMPUTEMESH_THESPORTSDB_API_KEY`.

## Security boundaries

### Public URL fetching

`fetch_web_content` accepts user-selected public HTTP(S) URLs, so it uses `url_security.py` rather than the trusted-provider helper. The guard:

- allows only HTTP/HTTPS;
- rejects URL credentials and internal DNS suffixes;
- rejects loopback, private, link-local, multicast, reserved, unspecified and otherwise non-global IPv4/IPv6 targets;
- fails closed if any current DNS answer is non-public;
- revalidates every redirect and the final URL;
- bounds redirect count, response bytes, output characters and request timeout.

`lookup_network_host` is owner-only and uses the same public-address policy. Its TLS check connects to a prevalidated public IP while retaining the original hostname for SNI/certificate verification.

### Trusted provider HTTP

Built-in providers whose hosts are constructed by ComputeMesh use `http_json.fetch_json`. It requires HTTPS, an exact host allowlist, a bounded response body, a finite timeout and valid UTF-8 JSON. It must not be used for arbitrary user-provided URLs.

### Calculator

`calculate_math` is a bounded mathematical evaluator, not a general Python runtime. The accepted AST excludes loops, comprehensions, imports, function/class definitions and arbitrary object methods. Calls and data sizes are bounded, and evaluation occurs in a disposable child process with a real timeout.

### Agent loop

The agent loop canonicalizes disabled tool names so aliases cannot bypass fleet policy. Invalid tool-argument JSON is returned as an error instead of being executed as `{}`. Model iterations, tool calls per iteration and tool-message size are bounded.

### External MCP stdio servers

External servers are operator-configured and all imported tools remain `owner_only`. RPC request/response transactions are serialized, response IDs are checked, calls have a finite timeout, and an unresponsive/desynchronized child is terminated. Child stderr is not left as an unread pipe.

The checked-in `mcp_config.json` is intentionally empty; it does not auto-launch an external process. A deployment that needs external MCP servers should supply an explicit operator-controlled configuration, for example:

```json
{
  "mcpServers": {
    "events": {
      "command": "python",
      "args": ["-m", "services.concert_research.mcp_server", "--transport", "stdio"],
      "timeoutSeconds": 15
    }
  }
}
```

## Tests

Core coverage is in:

- `services/mcp/tests/test_mcp_system.py`
- `services/mcp/tests/test_mcp_completion.py`
- `services/mcp/tests/test_mcp_url_security.py`
- `services/mcp/tests/test_mcp_client_hardening.py`
- `services/mcp/tests/test_mcp_agent_hardening.py`
- `services/mcp/tests/test_mcp_calc_hardening.py`

The repository CI compiles all Python sources and executes the full project test suite on pull requests to `main`.
