import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.billing.ledger import Ledger
from services.common.pricing import calculate_token_charge_micro
from services.gateway.agent_worker_runtime import build_gateway_agent_worker_runtime
from services.gateway.inference_backend import BackendResult
from services.mcp.config import MCPConfig
from services.mcp.platform.agent_definitions import AgentDefinition
from services.mcp.platform.session import AgentSessionStore, TurnStatus


class _Backend:
    def __init__(self):
        self.last_tools = None

    def complete(self, *, model_id, messages, max_tokens=None, tools=None):
        self.last_tools = tools
        return BackendResult("worker completed", 3, 2)


class _BillingBackend:
    def complete(self, *, model_id, messages, max_tokens=None, tools=None):
        return BackendResult(
            "worker billed",
            3,
            2,
            execution_job_id="agent-job-1",
            provider_shares=(("node-a", 1.0),),
        )


def _mesh_completion(_messages, _tools):
    return {
        "choices": [{"message": {"role": "assistant", "content": "mesh completed"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }


def _config(root: Path) -> MCPConfig:
    data = root / "data"
    return MCPConfig(
        agents_platform_enabled=True,
        agents_platform_registry_db=str(data / "registry.sqlite3"),
        agents_platform_memory_db=str(data / "memory.sqlite3"),
        agents_platform_audit_log=str(data / "audit.jsonl"),
        agents_platform_project_state=str(data / "project.json"),
        agents_platform_session_db=str(data / "sessions.sqlite3"),
        agents_platform_node_registry_db=str(data / "nodes.sqlite3"),
        agents_platform_lease_db=str(data / "leases.sqlite3"),
        agents_platform_artifact_root=str(data / "artifacts"),
        agents_platform_artifact_db=str(data / "artifacts.sqlite3"),
        agents_platform_usage_db=str(data / "usage.sqlite3"),
        agents_platform_trace_db=str(data / "traces.sqlite3"),
    )


class GatewayAgentWorkerRuntimeTests(unittest.TestCase):
    def test_mesh_preflight_can_keep_work_queued_until_a_verified_route_exists(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_MESH_PREFLIGHT_ENABLED": "1",
                }, clear=False):
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                        control_client=object(),
                    )
                _session, turn = store.create_task(
                    "mesh.agent",
                    "qwen2.5:3b",
                    "wait for a verified node",
                    principal_id="customer-1",
                    environment_type="mesh",
                )
                self.assertEqual(runtime.service.workers[0].run_once(limit=1), ())
                self.assertEqual(store.get_turn(turn.turn_id).status, TurnStatus.QUEUED)
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_worker_is_disabled_without_explicit_deployment_switch(self):
        with tempfile.TemporaryDirectory() as raw:
            store = AgentSessionStore(Path(raw) / "sessions.sqlite3")
            try:
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("COMPUTEMESH_AGENTS_WORKER_ENABLED", None)
                    self.assertIsNone(build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=store,
                        config=_config(Path(raw)),
                        repo_root=Path(raw),
                    ))
            finally:
                store.close()

    def test_enabled_worker_executes_gateway_queued_turn_through_existing_backend(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gateway_store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                }, clear=False):
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=gateway_store,
                        config=_config(root),
                        repo_root=root,
                    )
                self.assertIsNotNone(runtime)
                session, turn = gateway_store.create_task(
                    "mesh.agent",
                    "qwen2.5:3b",
                    "finish this task",
                    principal_id="customer-1",
                    tenant_id="tenant-1",
                )
                result = runtime.service.workers[0].run_once(limit=1)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                self.assertEqual(gateway_store.get_turn(turn.turn_id).status, TurnStatus.COMPLETED)
                items = gateway_store.list_items(session.session_id, turn_id=turn.turn_id)
                self.assertTrue(any(item.kind == "assistant" for item in items))
            finally:
                if runtime is not None:
                    runtime.close()
                gateway_store.close()

    def test_worker_uses_deployment_concurrency_and_fairness_settings(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                backend = _Backend()
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_WORKER_GLOBAL_LIMIT": "7",
                    "COMPUTEMESH_AGENTS_WORKER_PRINCIPAL_LIMIT": "2",
                    "COMPUTEMESH_AGENTS_WORKER_SESSION_LIMIT": "1",
                    "COMPUTEMESH_AGENTS_WORKER_TENANT_LIMIT": "3",
                    "COMPUTEMESH_AGENTS_WORKER_FAIR_PRINCIPALS": "0",
                    "COMPUTEMESH_AGENTS_WORKER_AGING_SECONDS": "17",
                    "COMPUTEMESH_AGENTS_WORKER_MAX_CANDIDATES": "23",
                    "COMPUTEMESH_AGENTS_WORKER_CONCURRENCY_LEASE_SECONDS": "45",
                    "COMPUTEMESH_AGENTS_WORKER_PERSISTENT_CONCURRENCY": "1",
                }, clear=False):
                    runtime = build_gateway_agent_worker_runtime(
                        backend=backend,
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                    )
                self.assertIsNotNone(runtime)
                gate = runtime.service.concurrency_gate
                self.assertIsNotNone(gate)
                self.assertEqual(gate.budget.global_limit, 7)
                self.assertEqual(gate.budget.principal_limit, 2)
                self.assertEqual(gate.budget.tenant_limit, 3)
                self.assertEqual(gate.lease_seconds, 45.0)
                policy = runtime.service.workers[0].scheduling_policy
                self.assertFalse(policy.fair_principals)
                self.assertEqual(policy.aging_interval_seconds, 17.0)
                self.assertEqual(policy.max_candidates, 23)
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_enabled_billing_reuses_gateway_ledger_for_agent_turn(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gateway_store = AgentSessionStore(root / "sessions.sqlite3")
            ledger = Ledger(root / "ledger.jsonl")
            ledger.deposit_customer_credits(
                customer_account_id="customer-1",
                amount_micro_units=100_000_000,
                payment_reference="agent-billing-test",
            )
            runtime = None
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "1",
                }, clear=False):
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_BillingBackend(),
                        session_store=gateway_store,
                        config=_config(root),
                        repo_root=root,
                        ledger=ledger,
                    )
                session, turn = gateway_store.create_task(
                    "mesh.agent",
                    "qwen2.5:3b",
                    "bill this task",
                    principal_id="customer-1",
                )
                result = runtime.service.workers[0].run_once(limit=1)
                self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                self.assertEqual(ledger.get_hold(f"agent_turn:{turn.turn_id}").status, "captured")
                expected = calculate_token_charge_micro("qwen2.5:3b", 3, 2)
                self.assertEqual(ledger.get_balance("customer-1"), 100_000_000 - expected)
                self.assertGreater(ledger.get_balance("provider:node-a"), 0)
                self.assertEqual(gateway_store.get_session(session.session_id).principal_id, "customer-1")
            finally:
                if runtime is not None:
                    runtime.close()
                gateway_store.close()

    def test_billing_rejects_a_ledger_without_the_existing_hold_contract(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gateway_store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "1",
                }, clear=False):
                    with self.assertRaises(RuntimeError):
                        build_gateway_agent_worker_runtime(
                            backend=_Backend(),
                            session_store=gateway_store,
                            config=_config(root),
                            repo_root=root,
                            ledger=object(),
                        )
            finally:
                if runtime is not None:
                    runtime.close()
                gateway_store.close()

    def test_billing_rejects_a_nonpersistent_hold_ledger(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gateway_store = AgentSessionStore(root / "sessions.sqlite3")
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "1",
                }, clear=False):
                    with self.assertRaises(RuntimeError):
                        build_gateway_agent_worker_runtime(
                            backend=_Backend(),
                            session_store=gateway_store,
                            config=_config(root),
                            repo_root=root,
                            ledger=Ledger(),
                        )
            finally:
                gateway_store.close()

    def test_mesh_turn_requires_explicit_authenticated_dispatch_switch(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED": "1",
                }, clear=False):
                    with self.assertRaises(RuntimeError):
                        build_gateway_agent_worker_runtime(
                            backend=_Backend(),
                            session_store=store,
                            config=_config(root),
                            repo_root=root,
                        )
            finally:
                store.close()

    def test_mesh_turn_uses_mesh_caller_and_keeps_legacy_backend_path(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                fake_control_client = object()
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED": "1",
                }, clear=False), patch(
                    "services.mcp.platform.runtime.AgentsPlatformRuntime.build_mesh_model_caller",
                    return_value=_mesh_completion,
                ) as build_mesh_caller:
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                        control_client=fake_control_client,
                    )
                    _session, turn = store.create_task(
                        "mesh.agent",
                        "qwen2.5:3b",
                        "run this on mesh",
                        principal_id="customer-1",
                        environment_type="mesh",
                    )
                    result = runtime.service.workers[0].run_once(limit=1)
                    self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                    self.assertEqual(build_mesh_caller.call_args.kwargs["control_client"], fake_control_client)
                    self.assertEqual(build_mesh_caller.call_args.kwargs["turn_id"], turn.turn_id)
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_mesh_billing_passes_private_evidence_observer_to_mesh_caller(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            ledger = Ledger(root / "ledger.jsonl")
            ledger.deposit_customer_credits(
                customer_account_id="customer-1",
                amount_micro_units=100_000_000,
                payment_reference="mesh-worker-billing",
            )
            runtime = None
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED": "1",
                }, clear=False), patch(
                    "services.mcp.platform.runtime.AgentsPlatformRuntime.build_mesh_model_caller",
                    return_value=_mesh_completion,
                ) as build_mesh_caller:
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                        control_client=object(),
                        ledger=ledger,
                    )
                    store.create_task(
                        "mesh.agent",
                        "qwen2.5:3b",
                        "bill this mesh turn",
                        principal_id="customer-1",
                        environment_type="mesh",
                    )
                    runtime.service.workers[0].run_once(limit=1)
                    self.assertTrue(callable(build_mesh_caller.call_args.kwargs["result_observer"]))
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_mesh_turn_projects_minimized_routing_requirements(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED": "1",
                }, clear=False), patch(
                    "services.mcp.platform.runtime.AgentsPlatformRuntime.build_mesh_model_caller",
                    return_value=_mesh_completion,
                ) as build_mesh_caller:
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                        control_client=object(),
                    )
                    store.create_task(
                        "mesh.agent",
                        "qwen2.5:3b",
                        "route with requirements",
                        principal_id="customer-1",
                        environment_type="mesh",
                        routing={
                            "required_capabilities": ["tool_call"],
                            "min_free_vram_bytes": 8_000,
                            "min_context_tokens": 16_000,
                            "min_decode_tokens_per_second": 20,
                            "max_latency_ms": 250,
                            "allowed_node_ids": ["node-a"],
                            "excluded_node_ids": ["node-b"],
                            "preferred_node_ids": ["node-a"],
                        },
                    )
                    result = runtime.service.workers[0].run_once(limit=1)
                    self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                    requirement = build_mesh_caller.call_args.kwargs["requirement"]
                    self.assertEqual(requirement.model_id, "qwen2.5:3b")
                    self.assertEqual(requirement.required_capabilities, frozenset({"inference_v1", "tool_call"}))
                    self.assertEqual(requirement.min_free_vram_bytes, 8_000)
                    self.assertEqual(requirement.preferred_node_ids, ("node-a",))
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_worker_binds_registered_definition_model_and_node_scope(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                backend = _Backend()
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_REQUIRE_DEFINITION": "1",
                }, clear=False), patch(
                    "services.mcp.platform.runtime.AgentsPlatformRuntime.build_mesh_model_caller",
                    return_value=_mesh_completion,
                ) as build_mesh_caller:
                    runtime = build_gateway_agent_worker_runtime(
                        backend=backend,
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                        control_client=object(),
                    )
                    assert runtime is not None
                    assert runtime.platform.agent_definition_store is not None
                    runtime.platform.agent_definition_store.register(AgentDefinition(
                        "mesh.agent",
                        "1",
                        {"allowed_models": ["qwen2.5:3b"]},
                        "mesh task",
                        tool_ids=("calculate_math",),
                        allowed_node_ids=("node-a",),
                    ))
                    _session, _turn = store.create_task(
                        "mesh.agent",
                        "qwen2.5:3b",
                        "run with the registered definition",
                        principal_id="customer-1",
                        environment_type="mesh",
                    )
                    result = runtime.service.workers[0].run_once(limit=1)
                    self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                    requirement = build_mesh_caller.call_args.kwargs["requirement"]
                    self.assertEqual(requirement.allowed_node_ids, frozenset({"node-a"}))
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_worker_applies_definition_tool_allowlist_to_backend_harness(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            backend = _Backend()
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_REQUIRE_DEFINITION": "1",
                }, clear=False):
                    runtime = build_gateway_agent_worker_runtime(
                        backend=backend,
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                    )
                assert runtime is not None
                assert runtime.platform.agent_definition_store is not None
                runtime.platform.agent_definition_store.register(AgentDefinition(
                    "tools.agent",
                    "1",
                    {"allowed_models": ["qwen2.5:3b"]},
                    "restricted task",
                    tool_ids=("calculate_math",),
                ))
                store.create_task(
                    "tools.agent",
                    "qwen2.5:3b",
                    "run with one tool",
                    principal_id="customer-1",
                )
                result = runtime.service.workers[0].run_once(limit=1)
                self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                self.assertEqual(
                    [tool["function"]["name"] for tool in (backend.last_tools or ())],
                    ["calculate_math"],
                )
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_worker_can_require_registered_definition_without_breaking_legacy_default(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            try:
                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                    "COMPUTEMESH_AGENTS_REQUIRE_DEFINITION": "1",
                }, clear=False):
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                    )
                store.create_task(
                    "unregistered.agent",
                    "qwen2.5:3b",
                    "must fail closed",
                    principal_id="customer-1",
                )
                result = runtime.service.workers[0].run_once(limit=1)
                self.assertEqual(result[0].status, TurnStatus.FAILED)
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()

    def test_runtime_policy_resolver_binds_minimized_policy_to_worker_harness(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = AgentSessionStore(root / "sessions.sqlite3")
            runtime = None
            resolved = []
            try:
                def resolve_policy(session, turn):
                    resolved.append((session.session_id, turn.turn_id))
                    return {
                        "decision_id": "apd_gateway_test",
                        "request_id": f"agent-turn:{turn.turn_id}",
                        "principal_id": session.principal_id,
                        "fleet_id": "fleet-test",
                        "allow_agents": True,
                        "allowed_tools": [],
                        "max_side_effect": "READ",
                        "expires_at": time.time() + 60,
                    }

                with patch.dict(os.environ, {
                    "COMPUTEMESH_AGENTS_WORKER_ENABLED": "1",
                    "COMPUTEMESH_AGENTS_BILLING_ENABLED": "0",
                }, clear=False):
                    runtime = build_gateway_agent_worker_runtime(
                        backend=_Backend(),
                        session_store=store,
                        config=_config(root),
                        repo_root=root,
                        runtime_policy_resolver=resolve_policy,
                    )
                session, turn = store.create_task(
                    "mesh.agent",
                    "qwen2.5:3b",
                    "run under the private policy envelope",
                    principal_id="customer-1",
                )
                result = runtime.service.workers[0].run_once(limit=1)
                self.assertEqual(result[0].status, TurnStatus.COMPLETED)
                self.assertEqual(resolved, [(session.session_id, turn.turn_id)])
            finally:
                if runtime is not None:
                    runtime.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
