"""Optional gateway wiring for durable ComputeMesh agent workers.

The HTTP gateway owns task admission and the Agents Platform owns execution.
This module joins those two existing contracts without changing the legacy
chat path. Worker startup is an explicit deployment choice; an unconfigured
gateway never consumes queued agent work implicitly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from services.gateway.agent_billing import AgentBillingEvidenceStore, GatewayAgentBilling
from services.gateway.inference_backend import InferenceBackend
from services.mcp.config import MCPConfig
from services.mcp.platform.contracts import RuntimePolicyEnvelope
from services.mcp.platform.model_caller import BackendModelCaller
from services.mcp.platform.node_routing import NodeRouteRequirement
from services.mcp.platform.runtime import AgentsPlatformRuntime
from services.mcp.platform.session import AgentSessionStore
from services.mcp.platform.worker import (
    AgentWorkerRequest,
    MeshAgentWorkerService,
    WorkerConcurrencyBudget,
    WorkerSchedulingPolicy,
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _optional_env_int(name: str, *, maximum: int) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return min(value, maximum)


@dataclass
class GatewayAgentWorkerRuntime:
    """Own the platform and worker service for one gateway process."""

    platform: AgentsPlatformRuntime
    service: MeshAgentWorkerService
    billing_evidence_store: AgentBillingEvidenceStore | None = None

    def start(self) -> Any:
        return self.service.start()

    def close(self, timeout: float | None = 5.0) -> bool:
        stopped = self.service.close(timeout)
        if stopped:
            self.platform.close()
            if self.billing_evidence_store is not None:
                self.billing_evidence_store.close()
        return stopped


def build_gateway_agent_worker_runtime(
    *,
    backend: InferenceBackend,
    session_store: AgentSessionStore,
    config: MCPConfig | None = None,
    repo_root: str | Path | None = None,
    tool_registry: Any | None = None,
    ledger: Any | None = None,
    control_client: Any | None = None,
    runtime_policy_resolver: Callable[[Any, Any], RuntimePolicyEnvelope | Mapping[str, Any] | None] | None = None,
) -> GatewayAgentWorkerRuntime | None:
    """Build the opt-in gateway worker against the existing inference backend.

    The runtime receives the same SQLite session path used by the HTTP task
    endpoints, so API-created turns become visible to workers across process
    boundaries. The worker executes as a non-owner principal; owner-only tools
    therefore cannot be reached merely because a task was admitted by the
    customer gateway.
    """
    if not _env_bool("COMPUTEMESH_AGENTS_WORKER_ENABLED"):
        return None
    if not callable(getattr(backend, "complete", None)):
        raise TypeError("gateway agent worker requires an inference backend")
    if not isinstance(session_store, AgentSessionStore):
        raise TypeError("gateway agent worker requires an AgentSessionStore")
    if runtime_policy_resolver is not None and not callable(runtime_policy_resolver):
        raise TypeError("gateway agent worker runtime policy resolver must be callable")

    effective_config = config or MCPConfig.from_env()
    if not effective_config.agents_platform_enabled:
        raise RuntimeError("gateway agent worker requires the Agents Platform to be enabled")
    # Keep the HTTP admission store and worker store on one durable contract,
    # even when the operator selected a custom session database path.
    effective_config = replace(
        effective_config,
        agents_platform_session_db=str(session_store.path),
    )
    platform = AgentsPlatformRuntime(
        config=effective_config,
        tool_registry=tool_registry,
        repo_root=repo_root,
    )
    if platform.session_store is None:
        platform.close()
        raise RuntimeError("gateway agent worker session store could not be initialized")
    mesh_dispatch_enabled = _env_bool("COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED")
    mesh_preflight_enabled = _env_bool("COMPUTEMESH_AGENTS_MESH_PREFLIGHT_ENABLED")
    if mesh_dispatch_enabled and control_client is None:
        platform.close()
        raise RuntimeError(
            "mesh agent dispatch requires an injected authenticated control client"
        )
    billing_enabled = _env_bool("COMPUTEMESH_AGENTS_BILLING_ENABLED")
    if billing_enabled and ledger is None:
        platform.close()
        raise RuntimeError("gateway agent billing requires the gateway ledger")
    if billing_enabled:
        required_billing_methods = ("create_hold", "get_hold", "renew_hold", "release_hold", "capture_hold")
        if any(not callable(getattr(ledger, method, None)) for method in required_billing_methods):
            platform.close()
            raise RuntimeError("gateway agent billing requires the existing credit hold/capture ledger")
        if getattr(ledger, "storage_path", None) is None:
            platform.close()
            raise RuntimeError("gateway agent billing requires a persistent ledger path")
    billing_evidence_store = None
    if billing_enabled:
        raw_evidence_path = os.environ.get("COMPUTEMESH_AGENTS_BILLING_EVIDENCE_DB", "").strip()
        ledger_path = getattr(ledger, "storage_path", None)
        evidence_path = Path(raw_evidence_path) if raw_evidence_path else None
        if evidence_path is None and ledger_path is not None:
            evidence_path = Path(ledger_path).with_name(f"{Path(ledger_path).stem}.agent-billing.sqlite3")
        if evidence_path is not None:
            billing_evidence_store = AgentBillingEvidenceStore(evidence_path)

    max_tokens = _env_int(
        "COMPUTEMESH_AGENTS_WORKER_MAX_TOKENS",
        1024,
        minimum=1,
        maximum=131_072,
    )
    configured_iterations = max(1, min(int(effective_config.max_agent_iterations), 20))
    worker_budget = WorkerConcurrencyBudget(
        global_limit=_env_int(
            "COMPUTEMESH_AGENTS_WORKER_GLOBAL_LIMIT",
            32,
            minimum=1,
            maximum=10_000,
        ),
        principal_limit=_env_int(
            "COMPUTEMESH_AGENTS_WORKER_PRINCIPAL_LIMIT",
            4,
            minimum=1,
            maximum=10_000,
        ),
        session_limit=_env_int(
            "COMPUTEMESH_AGENTS_WORKER_SESSION_LIMIT",
            1,
            minimum=1,
            maximum=10_000,
        ),
        tenant_limit=_optional_env_int(
            "COMPUTEMESH_AGENTS_WORKER_TENANT_LIMIT",
            maximum=10_000,
        ),
    )
    worker_scheduling = WorkerSchedulingPolicy(
        fair_principals=_env_bool("COMPUTEMESH_AGENTS_WORKER_FAIR_PRINCIPALS", True),
        aging_interval_seconds=_env_float(
            "COMPUTEMESH_AGENTS_WORKER_AGING_SECONDS",
            60.0,
            minimum=1.0,
            maximum=86_400.0,
        ),
        max_candidates=_env_int(
            "COMPUTEMESH_AGENTS_WORKER_MAX_CANDIDATES",
            500,
            minimum=1,
            maximum=5_000,
        ),
    )

    require_definition = _env_bool("COMPUTEMESH_AGENTS_REQUIRE_DEFINITION")

    def resolve_agent_definition(session: Any, model: str) -> tuple[Any | None, tuple[str, ...]]:
        """Resolve immutable agent policy without exposing its private payload."""
        definition_store = platform.agent_definition_store
        if definition_store is None:
            if require_definition:
                raise RuntimeError("agent definition registry is unavailable")
            return None, ()
        try:
            registered = definition_store.get(session.agent_id, session.agent_version)
        except KeyError:
            if require_definition:
                raise RuntimeError("agent definition is not registered")
            return None, ()

        definition = registered.definition
        strategy = definition.model_strategy
        if not isinstance(strategy, Mapping):
            raise RuntimeError("agent definition model strategy is invalid")
        fixed_model = str(strategy.get("model") or strategy.get("model_id") or "").strip()
        if fixed_model and fixed_model != model:
            raise RuntimeError("agent definition does not allow the requested model")
        allowed_models = strategy.get("allowed_models", strategy.get("models"))
        if allowed_models is not None:
            if not isinstance(allowed_models, (list, tuple, set, frozenset)):
                raise RuntimeError("agent definition model allowlist is invalid")
            if model not in {str(value) for value in allowed_models}:
                raise RuntimeError("agent definition does not allow the requested model")

        disabled_tools: tuple[str, ...] = ()
        if definition.tool_ids:
            allowed_tools = {str(value) for value in definition.tool_ids}
            disabled_tools = tuple(
                tool.name
                for tool in platform.tool_registry.list_tools(is_owner=False)
                if str(tool.name) not in allowed_tools
            )
        return registered, disabled_tools

    def resolve_request(session: Any, turn: Any) -> AgentWorkerRequest:
        model = str((session.state or {}).get("model") or "").strip()
        if not model:
            raise ValueError("agent session has no model binding")
        definition, _disabled_tools = resolve_agent_definition(session, model)
        is_mesh = str(getattr(session, "environment_type", "none") or "none") == "mesh"
        if is_mesh and not mesh_dispatch_enabled:
            raise RuntimeError(
                "mesh agent turns require COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED=1"
            )
        billing = (
            GatewayAgentBilling(
                ledger,
                model_id=model,
                max_tokens=max_tokens,
                max_iterations=configured_iterations,
                prompt_reserve_tokens=_env_int(
                    "COMPUTEMESH_AGENTS_BILLING_PROMPT_RESERVE_TOKENS",
                    max_tokens,
                    minimum=1,
                    maximum=1_000_000,
                ),
                evidence_store=billing_evidence_store,
            )
            if billing_enabled
            else None
        )
        if is_mesh:
            raw_routing = (session.state or {}).get("routing") or {}
            if not isinstance(raw_routing, Mapping):
                raise ValueError("agent session routing requirements are invalid")
            definition_nodes = tuple(definition.definition.allowed_node_ids) if definition is not None else ()
            requested_nodes = tuple(str(item) for item in raw_routing.get("allowed_node_ids", ()))
            if definition_nodes and requested_nodes:
                allowed_nodes = tuple(node_id for node_id in requested_nodes if node_id in definition_nodes)
                if not allowed_nodes:
                    raise RuntimeError("agent definition and task routing have no common node")
            else:
                allowed_nodes = requested_nodes or definition_nodes
            caller = platform.build_mesh_model_caller(
                control_client=control_client,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                model_id=model,
                requirement=NodeRouteRequirement(
                    model_id=model,
                    required_capabilities=frozenset(
                        {"inference_v1", *(str(item) for item in raw_routing.get("required_capabilities", ())) }
                    ),
                    min_free_vram_bytes=int(raw_routing.get("min_free_vram_bytes", 0)),
                    min_context_tokens=int(raw_routing.get("min_context_tokens", 0)),
                    min_decode_tokens_per_second=float(raw_routing.get("min_decode_tokens_per_second", 0.0)),
                    max_latency_ms=(
                        float(raw_routing["max_latency_ms"])
                        if raw_routing.get("max_latency_ms") is not None
                        else None
                    ),
                    allowed_node_ids=frozenset(allowed_nodes),
                    excluded_node_ids=frozenset(str(item) for item in raw_routing.get("excluded_node_ids", ())),
                    preferred_node_ids=tuple(str(item) for item in raw_routing.get("preferred_node_ids", ())),
                ),
                max_tokens=max_tokens,
                timeout_seconds=_env_float(
                    "COMPUTEMESH_AGENTS_MESH_TIMEOUT_SECONDS",
                    120.0,
                    minimum=1.0,
                    maximum=300.0,
                ),
                max_attempts=_env_int(
                    "COMPUTEMESH_AGENTS_MESH_MAX_ATTEMPTS",
                    1,
                    minimum=1,
                    maximum=4,
                ),
                result_observer=billing.observe if billing is not None else None,
            )
        else:
            caller = BackendModelCaller(
                backend=backend,
                model_id=model,
                max_tokens=max_tokens,
                result_observer=billing.observe if billing is not None else None,
            )
        return AgentWorkerRequest(
            model=model,
            llm_caller=caller,
            is_owner=False,
            max_iterations=configured_iterations,
            principal_id=session.principal_id,
            tenant_id=str((session.state or {}).get("tenant_id") or ""),
            billing_reserve=billing.reserve if billing is not None else None,
            billing_settle=billing.settle if billing is not None else None,
            billing_release=billing.release if billing is not None else None,
        )

    def mesh_preflight(session: Any, turn: Any) -> bool:
        """Keep mesh work queued until its verified model route is available."""
        if str(getattr(session, "environment_type", "none") or "none") != "mesh":
            return True
        if (
            not mesh_dispatch_enabled
            or not mesh_preflight_enabled
            or platform.node_registry is None
        ):
            return True
        model = str((session.state or {}).get("model") or "").strip()
        if not model:
            return False
        definition, _disabled_tools = resolve_agent_definition(session, model)
        raw_routing = (session.state or {}).get("routing") or {}
        if not isinstance(raw_routing, Mapping):
            return False
        definition_nodes = tuple(definition.definition.allowed_node_ids) if definition is not None else ()
        requested_nodes = tuple(str(item) for item in raw_routing.get("allowed_node_ids", ()))
        if definition_nodes and requested_nodes:
            allowed_nodes = tuple(node_id for node_id in requested_nodes if node_id in definition_nodes)
            if not allowed_nodes:
                return False
        else:
            allowed_nodes = requested_nodes or definition_nodes
        requirement = NodeRouteRequirement(
            model_id=model,
            required_capabilities=frozenset(
                {"inference_v1", *(str(item) for item in raw_routing.get("required_capabilities", ()))}
            ),
            min_free_vram_bytes=int(raw_routing.get("min_free_vram_bytes", 0)),
            min_context_tokens=int(raw_routing.get("min_context_tokens", 0)),
            min_decode_tokens_per_second=float(raw_routing.get("min_decode_tokens_per_second", 0.0)),
            max_latency_ms=(
                float(raw_routing["max_latency_ms"])
                if raw_routing.get("max_latency_ms") is not None
                else None
            ),
            allowed_node_ids=frozenset(allowed_nodes),
            excluded_node_ids=frozenset(str(item) for item in raw_routing.get("excluded_node_ids", ())),
            preferred_node_ids=tuple(str(item) for item in raw_routing.get("preferred_node_ids", ())),
        )
        return platform.route_node(requirement).selected is not None

    def harness_factory(session: Any, turn: Any, approved_ids: tuple[str, ...]) -> Any:
        model = str((session.state or {}).get("model") or "").strip()
        _definition, disabled_tools = resolve_agent_definition(session, model)
        runtime_policy = None
        if runtime_policy_resolver is not None:
            resolved_policy = runtime_policy_resolver(session, turn)
            if resolved_policy is not None:
                runtime_policy = (
                    resolved_policy
                    if isinstance(resolved_policy, RuntimePolicyEnvelope)
                    else RuntimePolicyEnvelope.from_mapping(resolved_policy)
                )
        return platform.build_agent_harness(
            is_owner=False,
            owner_id=session.principal_id or None,
            request_id=f"agent-turn:{turn.turn_id}",
            runtime_policy=runtime_policy,
            approved_approval_ids=approved_ids,
            disabled_tools=disabled_tools,
        )

    try:
        service = platform.build_agent_worker_service(
            request_resolver=resolve_request,
            harness_factory=harness_factory,
            worker_count=_env_int(
                "COMPUTEMESH_AGENTS_WORKER_COUNT",
                1,
                minimum=1,
                maximum=32,
            ),
            worker_prefix=os.environ.get("COMPUTEMESH_AGENTS_WORKER_PREFIX", "gateway-agent"),
            poll_interval=_env_float(
                "COMPUTEMESH_AGENTS_WORKER_POLL_SECONDS",
                0.25,
                minimum=0.01,
                maximum=60.0,
            ),
            batch_limit=_env_int("COMPUTEMESH_AGENTS_WORKER_BATCH", 1, minimum=1, maximum=100),
            persistent_concurrency=_env_bool("COMPUTEMESH_AGENTS_WORKER_PERSISTENT_CONCURRENCY", True),
            concurrency_budget=worker_budget,
            concurrency_lease_seconds=_env_float(
                "COMPUTEMESH_AGENTS_WORKER_CONCURRENCY_LEASE_SECONDS",
                300.0,
                minimum=5.0,
                maximum=86_400.0,
            ),
            scheduling_policy=worker_scheduling,
            preflight=mesh_preflight,
        )
    except Exception:
        platform.close()
        if billing_evidence_store is not None:
            billing_evidence_store.close()
        raise
    return GatewayAgentWorkerRuntime(platform, service, billing_evidence_store)


__all__ = ["GatewayAgentWorkerRuntime", "build_gateway_agent_worker_runtime"]
