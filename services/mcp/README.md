# ComputeMesh MCP and Live Tool Engine

ComputeMesh exposes built-in live-data tools through `ToolRegistry` and can also attach explicitly configured external MCP stdio/HTTP servers through `MCPClient`. The Agents Platform additionally provides an opt-in `MCPToolDiscoveryBroker` for bounded, origin-aware discovery without changing the legacy registry path.

## Built-in tool surface

With the normal configuration (`system_tools_enabled=false`) the registry exposes 25 built-in tools. Enabling the owner-only system information tool raises the total to 26.

| Area | Tools |
| --- | --- |
| Web/current information | `search_web`, `fetch_web_content`, `get_live_news` |
| Weather | `get_current_weather`, `get_weather_forecast` |
| Local discovery | `search_events`, `search_places`, `get_distance_route` |
| Markets/business | `get_market_quote`, `convert_currency`, `lookup_company`, `search_product_prices` |
| Sports/transit | `get_sports_data`, `lookup_train_schedule` |
| Reference/open data | `get_wikipedia_summary`, `lookup_country_data`, `get_world_bank_stats`, `search_arxiv_papers`, `lookup_food_product`, `lookup_software_package`, `get_recent_earthquakes`, `lookup_chemical_compound`, `lookup_word_definition` |
| Developer & Filesystem | `write_workspace_file`, `read_workspace_file`, `list_workspace_files`, `replace_file_content`, `multi_replace_file_content`, `grep_search_code`, `extract_code_symbols`, `run_terminal_command`, `run_project_tests`, `run_doctor_diagnostics` |
| Android & Play Store Automation | `validate_store_listing`, `validate_store_graphics`, `inspect_android_manifest_or_bundle`, `sync_play_console_metadata`, `adb_list_devices`, `adb_capture_screenshot`, `adb_install_app`, `adb_get_system_log` |
| Calculation/time | `calculate_math`, `get_time_and_calendar` |
| Owner-only diagnostics | `lookup_network_host`, optionally `get_system_info`, `get_gpu_telemetry` |

## Autonomous Operating Protocol (UAOP)

For multi-step, autonomous engineering tasks without human intervention, see the [Universal Autonomous Operating Protocol (UAOP)](./UAOP.md).


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

### Agent MCP discovery boundary

`AgentsPlatformRuntime.build_mcp_discovery_broker()` creates a broker without
starting configured servers. The caller must explicitly call `refresh()` to
perform discovery. `search()` returns bounded schema-free summaries, while
`describe()` loads a schema only for an exact qualified ID such as
`events__search`. Origin/server/tool policy is applied before both discovery
and execution, and `call()` is blocked unless its policy explicitly enables
execution. Results are size-bounded and secret-scanned before they are
returned. This boundary is intended for agent tool search; existing
`MCPClient.register_all_into_registry()` behavior remains compatible.

### Self-hosted workspace and approvals

`LocalWorkspaceTransport` supplies a shell-free `self_hosted` filesystem
workspace with bounded UTF-8 reads/writes, atomic replacement, path and
symlink checks, lease heartbeats and optional content-addressed artifact
writes. It is not an operating-system process sandbox; mesh environments must
use an authenticated NodeOS transport.

`AuthenticatedNodeEnvironmentTransport` is the typed NodeOS adapter for mesh
environments. It binds `prepare`, `heartbeat`, `execute` and `shutdown` to the
current authenticated session and issued lease, validates both wire schemas,
and requires the `mesh_environment_v1` capability. It deliberately has no
shell, command or arbitrary remote-execution fallback.
The authenticated control channel supports caller-bound request IDs and
cooperative cancellation. A handler may accept the cancellation token; the
transport never claims that an uninterruptible backend has already stopped.

Side-effecting agent tools create durable, principal-bound approval records in
the session store. The gateway exposes `/v1/agents/approvals` for listing and
`POST /v1/agents/approvals/{approval_id}` for an exact approve/reject decision.
The mobile/WebUI session panel consumes that optional API using the existing
localization layer. If a side-effecting tool is encountered inside the durable
agent harness, the turn enters `waiting_for_approval` and later tool calls in
the same batch are stopped. An approved continuation must present the same
session, turn, tool and argument digest; the durable approval is then consumed
atomically once. Approval resolution never stores raw arguments or executes a
side effect directly from the HTTP request.

`AgentSessionStore.create_task()` atomically creates the model-bound session
and its first queued turn. `MeshAgentWorker` claims queued or explicitly
resumed turns with a durable status transition and requires the deployment to
inject both a model caller and a policy-bound harness factory. It never
chooses a provider, shell or remote node implicitly. A resolver failure marks
only the claimed turn failed and cannot cause a second worker to replay it.

`BackendModelCaller` adapts an existing ComputeMesh `InferenceBackend` to the
worker contract, preserving backend token usage and passing tool schemas only
when the backend declares support. It does not create a second billing,
provider-selection or transport path.

An optional server-side `OpenAIAgentsClient` can bridge explicitly selected
sessions to the official OpenAI Agents API. It supports bounded session and
event requests, item retrieval and SSE events, but is disabled by default and
never replaces the local `MeshAgentHarness` implicitly. Its credential is read
only from the configured server environment; it is not available to Android,
NodeOS or mesh workspaces. Enablement requires the explicit
`COMPUTEMESH_AGENTS_OPENAI_ENABLED` rollout switch and deployment policy.

## Tests

Core coverage is in:

- `services/mcp/tests/test_mcp_system.py`
- `services/mcp/tests/test_mcp_completion.py`
- `services/mcp/tests/test_write_workspace_file.py`
- `services/mcp/tests/test_android_play_store_tools.py`
- `services/mcp/tests/test_mcp_url_security.py`
- `services/mcp/tests/test_mcp_client_hardening.py`
- `services/mcp/tests/test_agents_mcp_discovery.py`
- `services/mcp/tests/test_agents_worker.py`
- `services/mcp/tests/test_agents_model_caller.py`
- `services/mcp/tests/test_agents_openai_provider.py`
- `services/mcp/tests/test_mcp_agent_hardening.py`
- `services/mcp/tests/test_mcp_calc_hardening.py`


The repository CI compiles all Python sources and executes the full project test suite on pull requests to `main`.
