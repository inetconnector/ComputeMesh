"""Second-pass safety tests for write retries and emergency-stop enforcement."""
from __future__ import annotations

from unittest.mock import patch
import unittest

from services.mcp.config import MCPConfig
from services.mcp.platform.contracts import (
    RuntimePolicyEnvelope,
    SideEffectLevel,
    ToolExecutionContext,
    ToolManifest,
    ToolMode,
)
from services.mcp.platform.runtime import AgentsPlatformRuntime
from services.mcp.platform.tool_execution import SafeToolExecutor, ToolCapabilityRegistry
from services.mcp.tool_registry import ToolRegistry


class AmbiguousWriteBackend:
    def __init__(self) -> None:
        self.calls = 0

    def execute_tool(self, name, arguments, is_owner=True, owner_id=None):
        self.calls += 1
        return {"error": "ambiguous write failure"}


class PartialBackend:
    def __init__(self) -> None:
        self.calls = 0

    def execute_tool(self, name, arguments, is_owner=True, owner_id=None):
        self.calls += 1
        return {"items": [1], "error": "one item failed", "count": 1}


class OwnerCaptureRegistry:
    class _Tool:
        name = "read_tool"
        description = "read"
        parameters = {"type": "object", "properties": {}}
        owner_only = False
        source = "test"

        @staticmethod
        def to_openai_dict():
            return {
                "type": "function",
                "function": {
                    "name": "read_tool",
                    "description": "read",
                    "parameters": {"type": "object", "properties": {}},
                },
            }

    def __init__(self) -> None:
        self.owner_ids: list[str | None] = []
        self.tool = self._Tool()

    def list_tools(self, is_owner=True):
        return [self.tool]

    def get_tool(self, name):
        return self.tool if name == "read_tool" else None

    def get_openai_tools(self, is_owner=True):
        return [self.tool.to_openai_dict()]

    def execute_tool(self, name, arguments, is_owner=True, owner_id=None):
        self.owner_ids.append(owner_id)
        return {"ok": True}

    def execute_tools_batch(self, tool_calls, is_owner=True, owner_id=None, max_workers=8):
        raise AssertionError("not used")


class TestWriteRetrySafety(unittest.TestCase):
    def test_non_idempotent_write_is_never_blindly_retried(self) -> None:
        backend = AmbiguousWriteBackend()
        capabilities = ToolCapabilityRegistry()
        capabilities.register(ToolManifest(
            tool_id="write_tool",
            name="write_tool",
            side_effect=SideEffectLevel.WRITE_IRREVERSIBLE,
            confirmation_required=True,
            idempotent=False,
            retry_limit=4,
        ))
        executor = SafeToolExecutor(backend, capabilities)
        result = executor.execute(
            "write_tool",
            {"value": "x"},
            ToolExecutionContext(
                mode=ToolMode.EXECUTE,
                is_owner=True,
                authorized=True,
                confirmed=True,
                idempotency_key="idem-write-1",
            ),
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(backend.calls, 1)

    def test_partial_tool_result_is_not_retried_as_total_failure(self) -> None:
        backend = PartialBackend()
        capabilities = ToolCapabilityRegistry()
        capabilities.register(ToolManifest(
            tool_id="read_tool",
            name="read_tool",
            side_effect=SideEffectLevel.READ,
            confirmation_required=False,
            idempotent=True,
            retry_limit=3,
        ))
        executor = SafeToolExecutor(backend, capabilities)
        result = executor.execute(
            "read_tool",
            {},
            ToolExecutionContext(
                mode=ToolMode.EXECUTE,
                is_owner=True,
                authorized=True,
                confirmed=True,
            ),
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.provenance["result_status"], "PARTIAL_SUCCESS")
        self.assertEqual(backend.calls, 1)


class TestKillSwitchSafety(unittest.TestCase):
    def test_guard_failure_blocks_tool_execution(self) -> None:
        registry = ToolRegistry(MCPConfig())
        with patch(
            "runtime.safety.dead_mans_switch.get_lease_guard",
            side_effect=RuntimeError("guard unavailable"),
        ):
            result = registry.execute_tool(
                "calculate_math",
                {"expression": "1+1"},
                is_owner=True,
            )
        self.assertIn("error", result)
        self.assertIn("Sicherheitsprüfung", result["error"])

    def test_runtime_policy_fleet_binding_reaches_existing_kill_switch_scope(self) -> None:
        backend = OwnerCaptureRegistry()
        config = MCPConfig(
            agents_platform_enabled=True,
            agents_platform_shadow_mode=False,
            agents_platform_enforce_tool_policy=True,
            agents_platform_skill_roots="",
        )
        runtime = AgentsPlatformRuntime(config=config, tool_registry=backend)
        runtime.capabilities.register(ToolManifest(
            tool_id="read_tool",
            name="read_tool",
            side_effect=SideEffectLevel.READ,
            confirmation_required=False,
            idempotent=True,
        ))
        policy = RuntimePolicyEnvelope(
            decision_id="apd_fleet_scope",
            request_id="req_fleet_scope_001",
            allow_agents=True,
            principal_id="owner-a",
            fleet_id="fleet-a",
            allowed_tools=("read_tool",),
            max_side_effect=SideEffectLevel.READ,
            expires_at=9999999999.0,
        )
        loop = runtime.build_agent_loop(
            request_id=policy.request_id,
            runtime_policy=policy,
        )
        result = loop.registry.execute_tool("read_tool", {})
        self.assertTrue(result["ok"])
        self.assertEqual(backend.owner_ids, ["fleet-a"])


if __name__ == "__main__":
    unittest.main()
