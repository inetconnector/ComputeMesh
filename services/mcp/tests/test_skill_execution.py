"""Contract tests for the Universal Skill Execution System."""
from __future__ import annotations

import unittest

from services.mcp.skill_execution import (
    SkillExecutionEngine,
    SkillRegistry,
    SkillSpec,
    UNIVERSAL_SKILL,
    build_skill_engine,
)
from services.mcp.tool_registry import ToolRegistry


class TestSkillExecution(unittest.TestCase):
    def test_registry_selects_skill_and_returns_reproducible_plan(self) -> None:
        engine = SkillExecutionEngine(SkillRegistry((UNIVERSAL_SKILL,)))
        result = engine.build_plan("Erstelle einen validierten Arbeitsablauf für diese Recherche")
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["primary_skill"]["skill_id"], "universal_skill_execution")
        self.assertEqual(len(result["plan_digest"]), 64)
        self.assertIn("state", result)

    def test_missing_required_input_is_explicit(self) -> None:
        skill = SkillSpec(
            skill_id="required_input_skill",
            name="Required input",
            version="1.0",
            description="test",
            triggers=("analyse",),
            input_schema={"required": ["file"]},
        )
        result = SkillExecutionEngine(SkillRegistry((skill,))).build_plan("analyse", inputs={})
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["missing_inputs"], ["file"])

    def test_tool_failure_is_structured_and_not_success(self) -> None:
        engine = SkillExecutionEngine(SkillRegistry((UNIVERSAL_SKILL,)), tool_router=lambda *_: (_ for _ in ()).throw(RuntimeError("down")))
        result = engine.execute("Plane eine Aufgabe", tool_calls=[{"tool": "missing_tool", "arguments": {}}])
        self.assertEqual(result["status"], "partial_failure")
        self.assertEqual(result["results"][0]["error_class"], "TOOL_ERROR")
        self.assertFalse(result["quality_gate"]["correctness"])

    def test_tool_registry_exposes_owner_only_skill_tool(self) -> None:
        tool = ToolRegistry().get_tool("execute_universal_skill")
        self.assertIsNotNone(tool)
        self.assertTrue(tool.owner_only)

    def test_public_builder_has_universal_skill(self) -> None:
        self.assertEqual(build_skill_engine().registry.get("universal_skill_execution").version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
