"""Operational health snapshot tests for the Agents Platform."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.mcp.platform.health import collect_agents_platform_health


class _Registry:
    def health(self):
        return {"integrity": "ok", "counts": {"ACTIVE": 2}, "graph_errors": []}


class TestAgentsPlatformHealth(unittest.TestCase):
    def test_disabled_snapshot_does_not_require_components(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                agents_platform_enabled=False,
                agents_platform_shadow_mode=True,
                agents_platform_enforce_tool_policy=False,
            )
        )
        health = collect_agents_platform_health(runtime)
        self.assertEqual(health.status, "DISABLED")
        self.assertFalse(health.enabled)
        self.assertEqual(health.components, ())

    def test_shadow_snapshot_reports_non_secret_component_health(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / "memory.sqlite3"
            memory.write_bytes(b"sqlite")
            audit = Path(directory) / "audit.jsonl"
            audit.write_text("", encoding="utf-8")
            state = Path(directory) / "project_state.json"
            runtime = SimpleNamespace(
                config=SimpleNamespace(
                    agents_platform_enabled=True,
                    agents_platform_shadow_mode=True,
                    agents_platform_enforce_tool_policy=False,
                    agents_platform_routing_min_score=0.28,
                    agents_platform_routing_ambiguity_margin=0.08,
                ),
                skill_registry=_Registry(),
                router=object(),
                safe_tool_executor=object(),
                rule_resolver=object(),
                memory=SimpleNamespace(db_path=str(memory)),
                project_state=SimpleNamespace(state_path=state),
                audit=SimpleNamespace(path=audit),
                repo_root=Path(directory),
                initialization_errors=[],
            )
            health = collect_agents_platform_health(runtime)
            self.assertEqual(health.status, "SHADOW")
            self.assertTrue(health.enabled)
            names = {component.component for component in health.components}
            self.assertEqual(
                names,
                {"skill_registry", "skill_router", "tool_policy", "agents_rules", "memory", "project_state", "audit"},
            )
            serialized = health.to_dict()
            self.assertNotIn("secret", str(serialized).casefold())

    def test_initialization_error_degrades_status(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                agents_platform_enabled=True,
                agents_platform_shadow_mode=False,
                agents_platform_enforce_tool_policy=True,
                agents_platform_routing_min_score=0.28,
                agents_platform_routing_ambiguity_margin=0.08,
            ),
            skill_registry=None,
            router=None,
            safe_tool_executor=None,
            rule_resolver=None,
            memory=None,
            project_state=None,
            audit=None,
            repo_root=Path("."),
            initialization_errors=["registry:corrupt"],
        )
        health = collect_agents_platform_health(runtime)
        self.assertEqual(health.status, "DEGRADED")
        self.assertEqual(health.initialization_errors, ("registry:corrupt",))

    def test_enabled_remote_provider_without_credential_is_degraded_without_secret(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                agents_platform_enabled=True,
                agents_platform_shadow_mode=False,
                agents_platform_enforce_tool_policy=False,
                agents_platform_openai_agents_enabled=True,
                agents_platform_routing_min_score=0.28,
                agents_platform_routing_ambiguity_margin=0.08,
            ),
            skill_registry=None,
            router=None,
            safe_tool_executor=None,
            rule_resolver=None,
            memory=None,
            project_state=None,
            audit=None,
            openai_agents=SimpleNamespace(enabled=False),
            repo_root=Path("."),
            initialization_errors=[],
        )
        health = collect_agents_platform_health(runtime)
        provider = next(component for component in health.components if component.component == "openai_agents")
        self.assertEqual(provider.status, "DEGRADED")
        self.assertEqual(provider.detail["configured"], False)
        self.assertNotIn("credential", str(provider.detail).casefold().replace("credential_value_exposed", ""))


if __name__ == "__main__":
    unittest.main()
