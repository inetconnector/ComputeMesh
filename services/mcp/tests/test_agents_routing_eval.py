"""Dataset-driven regression evaluation for the Agents Platform skill router."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from services.mcp.platform.contracts import RequestEnvelope, SkillManifest
from services.mcp.platform.skill_registry import PersistentSkillRegistry
from services.mcp.platform.skill_router import SkillRouter


DATASET = Path(__file__).parent / "data" / "agents_routing_eval.json"


class TestAgentsRoutingEvaluation(unittest.TestCase):
    def test_dataset_expectations(self) -> None:
        cases = json.loads(DATASET.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 6)
        passed = 0
        for case in cases:
            with self.subTest(case=case["name"]):
                registry = PersistentSkillRegistry(":memory:")
                for raw in case["skills"]:
                    values = dict(raw)
                    for field_name in (
                        "triggers",
                        "negative_triggers",
                        "intents",
                        "domains",
                        "dependencies",
                    ):
                        values[field_name] = tuple(values.get(field_name, ()))
                    registry.register_manifest(SkillManifest(version="1.0.0", **values))
                envelope = RequestEnvelope.from_text(
                    case["request"],
                    explicit_skill=case.get("explicit_skill"),
                    context_budget=case.get("context_budget"),
                )
                decision = SkillRouter(registry).route(envelope)
                self.assertEqual(decision.status, case["expected_status"])
                expected_primary = case.get("expected_primary")
                if expected_primary:
                    self.assertTrue(decision.selected_skills)
                    self.assertEqual(decision.selected_skills[0], expected_primary)
                passed += 1
        self.assertEqual(passed, len(cases))


if __name__ == "__main__":
    unittest.main()
