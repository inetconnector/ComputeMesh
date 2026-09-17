"""Contract, persistence and security tests for ComputeMesh Agents Platform."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from services.mcp.config import MCPConfig
from services.mcp.platform.agents_rules import AgentsRuleResolver
from services.mcp.platform.contracts import (
    RequestEnvelope,
    SideEffectLevel,
    SkillManifest,
    SkillStatus,
    ToolExecutionContext,
    ToolManifest,
    ToolMode,
)
from services.mcp.platform.project_state import ProjectStateStore, StaleStateError
from services.mcp.platform.runtime import AgentsPlatformRuntime
from services.mcp.platform.skill_registry import PersistentSkillRegistry
from services.mcp.platform.skill_router import SkillRouter
from services.mcp.platform.tool_execution import SafeToolExecutor, ToolCapabilityRegistry
from services.memory.structured_memory import MemoryScope, MemoryType, StructuredMemoryStore


class FakeTool:
    def __init__(self, name: str, handler, *, owner_only: bool = False) -> None:
        self.name = name
        self.description = name
        self.parameters = {"type": "object", "properties": {}}
        self.handler = handler
        self.owner_only = owner_only
        self.source = "test"

    def to_openai_dict(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


class FakeToolRegistry:
    def __init__(self) -> None:
        self.calls = []
        self.tools = {
            "read_tool": FakeTool("read_tool", lambda **kwargs: {"ok": True, **kwargs}),
            "write_tool": FakeTool("write_tool", self._write),
        }

    def _write(self, **kwargs):
        self.calls.append(kwargs)
        return {"written": True, **kwargs}

    def list_tools(self, is_owner=True):
        return list(self.tools.values())

    def get_tool(self, name):
        return self.tools.get(name)

    def get_openai_tools(self, is_owner=True):
        return [tool.to_openai_dict() for tool in self.list_tools(is_owner)]

    def execute_tool(self, name, arguments, is_owner=True, owner_id=None):
        tool = self.tools.get(name)
        if not tool:
            return {"error": "not found"}
        if tool.owner_only and not is_owner:
            return {"error": "owner required"}
        return tool.handler(**arguments)

    def execute_tools_batch(self, tool_calls, is_owner=True, owner_id=None, max_workers=8):
        result = []
        for index, call in enumerate(tool_calls):
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            result.append({
                "id": call.get("id", f"call_{index}"),
                "name": fn.get("name", ""),
                "arguments": args,
                "result": self.execute_tool(fn.get("name", ""), args, is_owner=is_owner, owner_id=owner_id),
            })
        return result


class TestPersistentSkillRegistry(unittest.TestCase):
    def test_restart_persists_active_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skills"
            skill_dir = root / "demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nskill_id: demo.skill\nname: Demo\nversion: 1.0.0\ndescription: Demo skill\n"
                "status: ACTIVE\npriority: 70\ntriggers: [demo request]\n---\n# Workflow\nDo demo work.\n",
                encoding="utf-8",
            )
            db = Path(directory) / "registry.sqlite3"
            first = PersistentSkillRegistry(db, allowed_roots=(root,), available_tools=())
            self.assertEqual(first.discover()["loaded"], ["demo.skill@1.0.0"])
            first.close()
            second = PersistentSkillRegistry(db, allowed_roots=(root,), available_tools=())
            loaded = second.get("demo.skill", include_inactive=False)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.version, "1.0.0")
            second.close()

    def test_invalid_skill_fails_closed_and_is_recorded_broken(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skills"
            bad = root / "bad" / "SKILL.md"
            bad.parent.mkdir(parents=True)
            bad.write_text("not-frontmatter", encoding="utf-8")
            registry = PersistentSkillRegistry(Path(directory) / "registry.sqlite3", allowed_roots=(root,))
            result = registry.discover()
            self.assertEqual(result["loaded"], [])
            self.assertEqual(len(result["broken"]), 1)
            self.assertTrue(any(skill.status == SkillStatus.BROKEN for skill in registry.list()))

    def test_same_version_with_changed_checksum_is_rejected(self):
        registry = PersistentSkillRegistry(":memory:")
        first = SkillManifest("demo.skill", "Demo", "1.0.0", "first")
        registry.register_manifest(first)
        second = SkillManifest("demo.skill", "Demo", "1.0.0", "changed")
        with self.assertRaises(ValueError):
            registry.register_manifest(second)


class TestSkillRouter(unittest.TestCase):
    def _registry(self):
        registry = PersistentSkillRegistry(":memory:", available_tools={"read_tool"})
        registry.register_manifest(SkillManifest(
            "research.web", "Web research", "1.0.0", "Research current web sources",
            priority=80, domains=("research",), intents=("research",), triggers=("research the web", "recherche"),
            required_tools=("read_tool",), estimated_context_tokens=500,
        ))
        registry.register_manifest(SkillManifest(
            "research.private", "Private research", "1.0.0", "Research private sources",
            priority=79, domains=("research",), intents=("research",), triggers=("research private",),
            required_tools=("read_tool",), estimated_context_tokens=500,
        ))
        return registry

    def test_unknown_request_abstains(self):
        decision = SkillRouter(self._registry()).route(RequestEnvelope.from_text("hello there"), available_tools={"read_tool"})
        self.assertTrue(decision.abstained)
        self.assertEqual(decision.status, "ABSTAIN")

    def test_negative_trigger_excludes_skill(self):
        registry = self._registry()
        skill = SkillManifest(
            "danger.test", "Danger", "1.0.0", "Danger demo", priority=100,
            triggers=("danger",), negative_triggers=("do not danger",),
        )
        registry.register_manifest(skill)
        decision = SkillRouter(registry).route(RequestEnvelope.from_text("do not danger"), available_tools={"read_tool"})
        self.assertNotIn("danger.test", decision.selected_skills)

    def test_context_budget_causes_abstention(self):
        router = SkillRouter(self._registry())
        env = RequestEnvelope.from_text("research the web", context_budget=100)
        decision = router.route(env, available_tools={"read_tool"})
        self.assertTrue(decision.abstained)
        self.assertTrue(any("context_budget_exceeded" in reason for reason in decision.reasons))


class TestSafeToolExecution(unittest.TestCase):
    def test_write_requires_authorization_confirmation_and_idempotency(self):
        backend = FakeToolRegistry()
        capabilities = ToolCapabilityRegistry()
        capabilities.register(ToolManifest(
            "write_tool", "write_tool", side_effect=SideEffectLevel.WRITE_REVERSIBLE,
            confirmation_required=True, idempotent=False,
        ))
        executor = SafeToolExecutor(backend, capabilities)
        blocked = executor.execute("write_tool", {"x": 1}, ToolExecutionContext(mode=ToolMode.EXECUTE))
        self.assertEqual(blocked.status, "blocked")
        no_key = executor.execute("write_tool", {"x": 1}, ToolExecutionContext(
            mode=ToolMode.EXECUTE, is_owner=True, authorized=True, confirmed=True,
        ))
        self.assertEqual(no_key.status, "blocked")
        context = ToolExecutionContext(
            mode=ToolMode.EXECUTE, is_owner=True, authorized=True, confirmed=True, idempotency_key="abc",
        )
        first = executor.execute("write_tool", {"x": 1}, context)
        second = executor.execute("write_tool", {"x": 1}, context)
        self.assertEqual(first.status, "completed")
        self.assertTrue(second.idempotency_replay)
        self.assertEqual(len(backend.calls), 1)

    def test_idempotency_key_cannot_change_arguments(self):
        backend = FakeToolRegistry()
        capabilities = ToolCapabilityRegistry()
        capabilities.register(ToolManifest(
            "write_tool", "write_tool", side_effect=SideEffectLevel.WRITE_REVERSIBLE,
            confirmation_required=True, idempotent=False,
        ))
        executor = SafeToolExecutor(backend, capabilities)
        context = ToolExecutionContext(mode=ToolMode.EXECUTE, authorized=True, confirmed=True, idempotency_key="same")
        self.assertEqual(executor.execute("write_tool", {"x": 1}, context).status, "completed")
        changed = executor.execute("write_tool", {"x": 2}, context)
        self.assertEqual(changed.status, "blocked")
        self.assertIn("different arguments", changed.error)


class TestAgentsRulesAndState(unittest.TestCase):
    def test_nested_agents_rules_are_root_to_leaf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("root rule", encoding="utf-8")
            nested = root / "services" / "demo"
            nested.mkdir(parents=True)
            (root / "services" / "AGENTS.md").write_text("service rule", encoding="utf-8")
            target = nested / "file.py"
            target.write_text("x=1", encoding="utf-8")
            resolution = AgentsRuleResolver(root).resolve(target)
            self.assertEqual([doc.content for doc in resolution.documents], ["root rule", "service rule"])

    def test_project_state_detects_stale_write_and_restores_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectStateStore(Path(directory) / "state.json")
            initial = store.initialize("P1", "Demo", "Goal")
            checkpoint = store.checkpoint(expected_version=initial.version)
            updated = store.update(lambda data: data.update({"status": "UPDATED"}), expected_version=initial.version)
            with self.assertRaises(StaleStateError):
                store.save(updated.data, expected_version=initial.version)
            restored = store.restore_checkpoint(checkpoint["checkpoint_id"], expected_version=updated.version)
            self.assertEqual(restored.data["status"], "ACTIVE")


class TestStructuredMemory(unittest.TestCase):
    def test_scope_isolation_expiry_conflicts_and_delete_cascade(self):
        store = StructuredMemoryStore(":memory:")
        user_a = store.put("favorite", "red", scope=MemoryScope.USER, scope_id="A", provenance="user")
        store.put("favorite", "blue", scope=MemoryScope.USER, scope_id="B", provenance="user")
        self.assertEqual([r.value for r in store.retrieve("favorite", scope=MemoryScope.USER, scope_id="A")], ["red"])
        store.put("favorite", "green", scope=MemoryScope.USER, scope_id="A", provenance="correction", memory_type=MemoryType.CORRECTION)
        self.assertGreaterEqual(len(store.conflicts("favorite", scope=MemoryScope.USER, scope_id="A")), 2)
        derived = store.put("derived", "from red", scope=MemoryScope.USER, scope_id="A", provenance="derived", explicit=False, derived_from=(user_a.memory_id,))
        self.assertEqual(store.delete(user_a.memory_id, scope=MemoryScope.USER, scope_id="A", cascade_derived=True), 2)
        self.assertIsNotNone(store.get(derived.memory_id).deleted_at)
        store.put("temp", "soon gone", scope=MemoryScope.USER, scope_id="A", provenance="session", memory_type=MemoryType.TEMPORARY, valid_until=time.time() - 1)
        store.purge_expired()
        self.assertFalse(any(r.key == "temp" for r in store.list_active(scope=MemoryScope.USER, scope_id="A")))

    def test_legacy_json_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "user_profile.json"
            legacy.write_text(json.dumps({
                "profile": {"name": "Ada", "preferred_language": "Deutsch", "preferences": ["concise"], "facts": ["tester"]},
                "memories": {"project": {"value": "ComputeMesh", "category": "work"}},
            }), encoding="utf-8")
            store = StructuredMemoryStore(":memory:")
            first = store.import_legacy_json(legacy, scope_id="u1")
            second = store.import_legacy_json(legacy, scope_id="u1")
            self.assertEqual(first["status"], "imported")
            self.assertEqual(second["status"], "already_imported")


class TestFeatureGatedRuntime(unittest.TestCase):
    def test_disabled_runtime_stays_legacy(self):
        config = MCPConfig(agents_platform_enabled=False)
        runtime = AgentsPlatformRuntime(config=config, tool_registry=FakeToolRegistry(), repo_root=Path.cwd())
        preparation = runtime.prepare([{"role": "user", "content": "research"}])
        self.assertFalse(preparation.enabled)
        self.assertIsNone(preparation.routing)

    def test_shadow_mode_routes_without_injecting_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "skills" / "demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nskill_id: demo.skill\nname: Demo\nversion: 1.0.0\ndescription: demo\nstatus: ACTIVE\ntriggers: [demo]\n---\n",
                encoding="utf-8",
            )
            config = MCPConfig(
                agents_platform_enabled=True,
                agents_platform_shadow_mode=True,
                agents_platform_skill_roots="skills",
                agents_platform_registry_db="data/registry.sqlite3",
                agents_platform_memory_db="data/memory.sqlite3",
                agents_platform_audit_log="data/audit.jsonl",
                agents_platform_project_state="data/state.json",
            )
            runtime = AgentsPlatformRuntime(config=config, tool_registry=FakeToolRegistry(), repo_root=root)
            prep = runtime.prepare([{"role": "user", "content": "demo please"}])
            self.assertTrue(prep.enabled)
            self.assertTrue(prep.shadow_mode)
            self.assertEqual(prep.context_sections, ())
            self.assertEqual(prep.routing["status"], "ROUTED")


if __name__ == "__main__":
    unittest.main()
