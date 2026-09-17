# ComputeMesh Configuration & Environment Variables Guide

This guide provides a complete, authoritative reference of all environment variables, feature flags, configuration switches, and default values across the **ComputeMesh Gateway**, **Agents Platform**, **MCP Subsystem**, **Security/Killswitches**, and **ControlPlane**.

---

## 1. Agents Platform & Orchestration (`COMPUTEMESH_AGENTS_*`)

These switches govern the modular, DAG-based multi-agent orchestration engine, skill discovery, routing, and persistent memory.

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `COMPUTEMESH_AGENTS_PLATFORM_ENABLED` | Boolean | `true` | **Master Switch**: Enables the new Agents Platform DAG runtime. When `false`, falls back to legacy direct tool loop. |
| `COMPUTEMESH_AGENTS_PLATFORM_SHADOW_MODE` | Boolean | `false` | **Shadow Mode**: When `true`, runs skill routing, analysis, and audits passively in the background without modifying prompts or tool execution. Set to `false` for fully active DAG execution. |
| `COMPUTEMESH_AGENTS_ENFORCE_TOOL_POLICY` | Boolean | `false` | **Strict Policy Enforcement**: Enforces 4-step tool discipline (Preview → Confirm → Execute → Verify) and fine-grained authorization grants on all side-effecting tools. |
| `COMPUTEMESH_AGENTS_SKILL_ROOTS` | String | `skills;services/mcp` | Semicolon-separated directory paths searched for `SKILL.md` skill definitions and manifests. |
| `COMPUTEMESH_AGENTS_REGISTRY_DB` | Path | `data/agents/skill_registry.sqlite3` | SQLite database storing discovered skills, versions, checksums, and validation status. |
| `COMPUTEMESH_AGENTS_MEMORY_DB` | Path | `data/agents/memory.sqlite3` | SQLite database for structured, scope-isolated long-term memory (User, Fleet, Project, Session scopes). |
| `COMPUTEMESH_AGENTS_AUDIT_LOG` | Path | `data/agents/audit.jsonl` | Append-only JSONL log recording every prompt routing decision, tool execution, and policy check. |
| `COMPUTEMESH_AGENTS_PROJECT_STATE` | Path | `data/agents/project_state.json` | Compare-and-swap (CAS) state file for distributed workflow and project checkpoints. |
| `COMPUTEMESH_AGENTS_ROUTING_MIN_SCORE` | Float | `0.28` | Minimum semantic/lexical confidence score required to route a request to a skill (below this, the router abstains). |
| `COMPUTEMESH_AGENTS_ROUTING_AMBIGUITY_MARGIN` | Float | `0.08` | Score difference threshold between top candidate skills before flagging an ambiguous request. |

---

## 2. Model Context Protocol (MCP) & Built-in Tools (`COMPUTEMESH_MCP_*`)

Controls live data tools, APIs, code interpreter, and external MCP servers.

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `COMPUTEMESH_MCP_ENABLED` | Boolean | `true` | **Master MCP Switch**: Enables tool calling capabilities for chat completions. |
| `COMPUTEMESH_MCP_MAX_ITERATIONS` | Integer | `5` | Maximum autonomous agent tool-calling iterations allowed per user prompt. |
| `COMPUTEMESH_MCP_TIMEOUT_SECONDS` | Float | `15.0` | Network timeout in seconds for HTTP/REST tool calls. |
| `COMPUTEMESH_MCP_WEB_SEARCH_ENABLED` | Boolean | `true` | Enables live web search (`search_web`, `cross_source_knowledge_search`, Wikipedia). |
| `COMPUTEMESH_MCP_FINANCE_ENABLED` | Boolean | `true` | Enables real-time market and cryptocurrency quotes (`get_market_quote`). |
| `COMPUTEMESH_MCP_WEB_FETCH_ENABLED` | Boolean | `true` | Enables direct URL scraping and content fetching (`fetch_web_page`). |
| `COMPUTEMESH_MCP_SYSTEM_TOOLS_ENABLED` | Boolean | `false` | Enables local command execution (`run_terminal_command`) for authenticated cluster owners. |
| `COMPUTEMESH_MCP_CONFIG_PATH` | Path | `""` | Optional path to custom JSON file defining external stdio/SSE MCP server connections. |
| `COMPUTEMESH_THESPORTSDB_API_KEY` | String | *(free tier)* | API key for sports data integration (`get_sports_data`). |

---

## 3. Gateway, Inferences & Routing

Governs the OpenAI-compatible HTTP server (`/v1/chat/completions`, `/v1/models`).

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `COMPUTEMESH_GATEWAY_HOST` | String | `127.0.0.1` | Network interface address the gateway binds to. |
| `COMPUTEMESH_GATEWAY_PORT` | Integer | `18000` | HTTP port for the OpenAI-compatible gateway. |
| `COMPUTEMESH_INFERENCE_BACKEND` | String | `auto` | Backend adapter (`llama_cpp`, `ollama`, `vllm`, `mock`). |
| `COMPUTEMESH_DEFAULT_MODEL` | String | `qwen/qwen2.5-7b-instruct` | Fallback model ID when none is specified in client request. |
| `COMPUTEMESH_MODEL_REGISTRY_URL` | URL | `""` | Remote URL endpoint for dynamic model catalogue synchronisation. |
| `COMPUTEMESH_PROVIDER_SHARES` | String | `""` | JSON or comma-separated mapping of provider node IDs to revenue shares. |
| `COMPUTEMESH_DEFAULT_PROVIDER_NODE_ID` | String | `node_test_settle_02` | Default provider node credited during live testmode settlements. |

---

## 4. Security, Authentication & Killswitches

Defines administrative access, owner keys, passkey vaults, and emergency stops.

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `COMPUTEMESH_MASTER_ADMIN_KEY` | String | `""` | Master administrative secret for privileged management, node bans, and killswitches. |
| `COMPUTEMESH_ADMIN_KEY` | String | `""` | Secondary admin key for fleet operations. |
| `COMPUTEMESH_KILL_SWITCH_ACTIVE` | Boolean | `false` | **Global Emergency Stop**: When `true`, all inference and tool executions are instantly blocked. |
| `COMPUTEMESH_KILL_SWITCH_REASON` | String | `""` | Explanatory message returned to clients when kill switch is tripped. |
| `COMPUTEMESH_VAULT_DIR` | Path | `data/vault/` | Secure local storage directory for WebAuthn passkey credentials and sessions. |
| `ALLOWED_DOMAINS` | String | `*` | Comma-separated domain allowlist for native Playwright browser automation tools. |

---

## 5. Billing & Ledger (`COMPUTEMESH_STRIPE_*`)

Handles credits, balances, and Stripe webhooks.

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `COMPUTEMESH_STRIPE_SECRET_KEY` | String | `""` | Stripe secret API key for checkout sessions. |
| `COMPUTEMESH_STRIPE_WEBHOOK_SECRET` | String | `""` | Stripe webhook signing secret for deposit verifications. |
| `COMPUTEMESH_PUBLIC_BASE_URL` | URL | `https://mesh.inetconnector.com` | Public base URL used for OAuth/Stripe redirect callbacks. |
| `COMPUTEMESH_FREE_TEASER_LIMIT` | Integer | `20` | Number of free teaser requests allowed per client IP before requiring an API key. |

---

## 6. ControlPlane & Cluster Nodes

Manages private provider dispatch, health checks, and clustering telemetry.

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `COMPUTEMESH_CONTROL_PLANE_HOST` | String | `127.0.0.1` | ControlPlane service host. |
| `COMPUTEMESH_CONTROL_PLANE_PORT` | Integer | `8443` | ControlPlane HTTPS/gRPC port. |
| `COMPUTEMESH_CURRENT_FLEET_ID` | String | `primary` | Unique cluster fleet identifier for multi-tenant isolation. |
| `COMPUTEMESH_PRODUCTION_MODE` | String | `0` | Set to `1` to enforce strict provider compliance policies and reject unsigned builds. |
| `COMPUTEMESH_CONFIDENTIAL_LEASE_SECONDS` | Integer | `120` | Hardware lease heartbeat timeout for confidential GPU execution. |

---

## 7. Example `.env` Configuration File

To customize your local or production deployment, create a `.env` file in the project root:

```bash
# === Agents Platform (Active Mode) ===
COMPUTEMESH_AGENTS_PLATFORM_ENABLED=true
COMPUTEMESH_AGENTS_PLATFORM_SHADOW_MODE=false
COMPUTEMESH_AGENTS_ENFORCE_TOOL_POLICY=false
COMPUTEMESH_AGENTS_ROUTING_MIN_SCORE=0.28

# === Model Context Protocol (MCP) ===
COMPUTEMESH_MCP_ENABLED=true
COMPUTEMESH_MCP_MAX_ITERATIONS=5
COMPUTEMESH_MCP_TIMEOUT_SECONDS=15.0
COMPUTEMESH_MCP_WEB_SEARCH_ENABLED=true
COMPUTEMESH_MCP_FINANCE_ENABLED=true

# === Gateway & Inference ===
COMPUTEMESH_GATEWAY_PORT=18000
COMPUTEMESH_DEFAULT_MODEL=qwen/qwen2.5-7b-instruct
COMPUTEMESH_FREE_TEASER_LIMIT=20

# === Security ===
COMPUTEMESH_MASTER_ADMIN_KEY=your-secure-master-key-here
ALLOWED_DOMAINS=*
```
