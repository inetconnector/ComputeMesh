"""Integration contracts for the public Agents Platform orchestration pipeline."""
from __future__ import annotations

import unittest

from services.mcp.platform.contracts import SkillManifest
from services.mcp.platform.pipeline import AgentsOrchestrationPipeline
from services.mcp.platform.skill_registry import PersistentSkillRegistry


class TestAgentsOrchestrationPipeline(unittest.TestCase):
    def _registry(self) -> PersistentSkillRegistry:
        registry = PersistentSkillRegistry(":memory:")
        registry.register_manifest(
            SkillManifest(
                skill_id="extract.skill",
                name="Extract",
                version="1.0.0",
                description="extract data",
                triggers=("extract",),
                priority=90,
                validation_rules=("not_none", "no_error_field"),
            )
        )
        registry.register_manifest(
            SkillManifest(
                skill_id="report.skill",
                name="Report",
                version="1.0.0",
                description="create report",
                triggers=("report",),
                priority=80,
                dependencies=("extract.skill",),
                validation_rules=("not_none", "no_error_field"),
            )
        )
        return registry

    def test_prepare_returns_analysis_route_and_executable_tasks(self) -> None:
        pipeline = AgentsOrchestrationPipeline(self._registry())
        plan = pipeline.prepare("create report", explicit_skill="report.skill")
        self.assertEqual(plan.routing.status, "ROUTED")
        self.assertEqual(set(plan.routing.selected_skills), {"extract.skill", "report.skill"})
        by_skill = {task.skill_id: task for task in plan.tasks}
        self.assertEqual(by_skill["report.skill"].dependencies, ("skill:extract.skill",))
        self.assertTrue(plan.analysis.intents)

    def test_execute_respects_dependency_order_and_validation(self) -> None:
        pipeline = AgentsOrchestrationPipeline(self._registry())
        plan = pipeline.prepare("create report", explicit_skill="report.skill")
        calls: list[str] = []

        def runner(task):
            calls.append(task.skill_id)
            return {"ok": task.skill_id}

        result = pipeline.execute("pipeline-1", plan, runner)
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(calls, ["extract.skill", "report.skill"])

    def test_validation_failure_prevents_dependent_success(self) -> None:
        pipeline = AgentsOrchestrationPipeline(self._registry())
        plan = pipeline.prepare("create report", explicit_skill="report.skill")

        def runner(task):
            if task.skill_id == "extract.skill":
                return {"error": "bad extraction"}
            return {"should_not_run": True}

        result = pipeline.execute("pipeline-2", plan, runner)
        by_id = {node.node_id: node for node in result.nodes}
        self.assertEqual(result.status, "PARTIAL_FAILURE")
        self.assertEqual(by_id["skill:extract.skill"].status, "FAILED")
        self.assertEqual(by_id["skill:report.skill"].status, "BLOCKED")

    def test_unrouted_plan_cannot_execute(self) -> None:
        pipeline = AgentsOrchestrationPipeline(PersistentSkillRegistry(":memory:"))
        plan = pipeline.prepare("nothing matches")
        self.assertEqual(plan.routing.status, "ABSTAIN")
        with self.assertRaises(ValueError):
            pipeline.execute("pipeline-3", plan, lambda task: {})


if __name__ == "__main__":
    unittest.main()
