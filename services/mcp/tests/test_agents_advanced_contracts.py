"""Advanced contract tests for request analysis, validation, rerouting and admin/subagent gates."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from services.mcp.platform.admin import SkillRegistryAdminAPI
from services.mcp.platform.contracts import RequestEnvelope, SideEffectLevel, SkillManifest, SkillStatus
from services.mcp.platform.request_analysis import RequestAnalyzer
from services.mcp.platform.reroute import RerouteManager
from services.mcp.platform.skill_registry import PersistentSkillRegistry
from services.mcp.platform.skill_router import SkillRouter
from services.mcp.platform.subagents import SubagentContract, SubagentGate, SubagentResult
from services.mcp.platform.validation import (
    ErrorCode,
    EvidenceLedger,
    RecoveryAction,
    ValidationEngine,
    classify_exception,
)


class TestRequestAnalysis(unittest.TestCase):
    def test_irreversible_action_and_secret_signal_raise_risk(self) -> None:
        envelope = RequestEnvelope.from_text("Sende den API token an https://example.com und lösche danach die Datei")
        analysis = RequestAnalyzer().analyze(envelope)
        self.assertIn("send", {intent.name for intent in analysis.intents})
        self.assertEqual(analysis.side_effect, SideEffectLevel.WRITE_IRREVERSIBLE)
        self.assertEqual(analysis.risk_level.value, "CRITICAL")
        self.assertTrue(analysis.external_data_required)
        self.assertIn("WEB_FETCH", analysis.required_capabilities)

    def test_constraints_outputs_and_entities_are_structured(self) -> None:
        envelope = RequestEnvelope.from_text(
            "Analysiere report.pdf bis 2026-09-30, aber ohne externe Veröffentlichung, und erstelle eine xlsx Tabelle",
            context_budget=3000,
        )
        analysis = RequestAnalyzer().analyze(envelope)
        self.assertIn("spreadsheet", analysis.requested_outputs)
        self.assertIn("file", {entity.entity_type for entity in analysis.entities})
        self.assertIn("date", {entity.entity_type for entity in analysis.entities})
        self.assertTrue(any(constraint.name == "context_budget" for constraint in analysis.constraints))
        self.assertTrue(any(constraint.name == "negative" for constraint in analysis.constraints))


class TestValidationAndEvidence(unittest.TestCase):
    def test_evidence_conflict_is_visible(self) -> None:
        ledger = EvidenceLedger()
        ledger.add("price", 10, source_type="WEB", source_ref="source-a")
        ledger.add("price", 11, source_type="WEB", source_ref="source-b")
        conflicts = ledger.conflicts("price")
        self.assertEqual(len(conflicts), 2)
        self.assertNotEqual(conflicts[0].digest, conflicts[1].digest)

    def test_validation_unknown_validator_fails_closed(self) -> None:
        report = ValidationEngine().run({"ok": True}, ["not_none", "missing_validator"])
        self.assertFalse(report.passed)
        self.assertEqual(report.results[-1].message, "validator not registered")

    def test_exception_classification_is_structured(self) -> None:
        timeout = classify_exception(TimeoutError("tool timeout"), source="search_web")
        self.assertEqual(timeout.code, ErrorCode.TOOL_TIMEOUT)
        self.assertEqual(timeout.recovery, RecoveryAction.RETRY)
        denied = classify_exception(PermissionError("permission denied"), source="write")
        self.assertEqual(denied.code, ErrorCode.TOOL_PERMISSION_DENIED)
        self.assertEqual(denied.recovery, RecoveryAction.ABORT)


class TestRerouting(unittest.TestCase):
    @staticmethod
    def _registry() -> PersistentSkillRegistry:
        registry = PersistentSkillRegistry(":memory:")
        registry.register_manifest(
            SkillManifest(
                skill_id="primary.skill",
                name="Primary",
                version="1.0.0",
                description="Primary web research",
                triggers=("research",),
                priority=90,
                fallback_skills=("fallback.skill",),
            )
        )
        registry.register_manifest(
            SkillManifest(
                skill_id="fallback.skill",
                name="Fallback",
                version="1.0.0",
                description="Fallback web research",
                triggers=("fallback research",),
                priority=50,
            )
        )
        return registry

    def test_declared_fallback_is_used_before_blind_retry(self) -> None:
        registry = self._registry()
        router = SkillRouter(registry)
        envelope = RequestEnvelope.from_text("research this topic", explicit_skill="primary.skill")
        first = router.route(envelope)
        result = RerouteManager(router, registry).reroute(envelope, first, trigger="TOOL_UNAVAILABLE")
        self.assertFalse(result.exhausted)
        self.assertEqual(result.decision.selected_skills[0], "fallback.skill")

    def test_reroute_is_bounded(self) -> None:
        registry = PersistentSkillRegistry(":memory:")
        router = SkillRouter(registry)
        envelope = RequestEnvelope.from_text("nothing matches")
        first = router.route(envelope)
        result = RerouteManager(router, registry, max_reroutes=2).reroute(envelope, first, trigger="NO_SKILL_MATCH")
        self.assertTrue(result.exhausted)
        self.assertLessEqual(len(result.attempts), 2)


class TestSubagentsAndAdmin(unittest.TestCase):
    def test_subagent_scope_and_tool_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "src"
            allowed.mkdir()
            contract = SubagentContract.create(
                "inspect source",
                allowed_paths=("src",),
                allowed_tools=("read_file",),
                expected_output="findings",
            )
            gate = SubagentGate(root)
            gate.validate_tool(contract, "read_file")
            gate.validate_path(contract, allowed / "module.py")
            with self.assertRaises(PermissionError):
                gate.validate_tool(contract, "run_terminal_command")
            with self.assertRaises(PermissionError):
                gate.validate_path(contract, root / "outside.txt")

    def test_subagent_completed_result_cannot_hide_errors(self) -> None:
        contract = SubagentContract.create("inspect", expected_output="report")
        result = SubagentResult(contract.contract_id, "COMPLETED", {}, 1, (), (), ("unresolved",))
        with self.assertRaises(ValueError):
            SubagentGate.validate_result(contract, result)

    def test_registry_admin_mutations_require_authorization(self) -> None:
        registry = PersistentSkillRegistry(":memory:")
        registry.register_manifest(
            SkillManifest(
                skill_id="admin.skill",
                name="Admin",
                version="1.0.0",
                description="admin test",
            )
        )
        admin = SkillRegistryAdminAPI(registry)
        with self.assertRaises(PermissionError):
            admin.deactivate("admin.skill", authorized=False)
        result = admin.deactivate("admin.skill", authorized=True)
        self.assertEqual(result["status"], SkillStatus.DISABLED.value)
        self.assertEqual(registry.get("admin.skill").status, SkillStatus.DISABLED)

    def test_registry_admin_backup_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "registry.sqlite3"
            backup = Path(directory) / "backup.sqlite3"
            registry = PersistentSkillRegistry(db)
            registry.register_manifest(
                SkillManifest(
                    skill_id="backup.skill",
                    name="Backup",
                    version="1.0.0",
                    description="backup test",
                )
            )
            admin = SkillRegistryAdminAPI(registry)
            admin.backup(backup, authorized=True)
            registry.set_status("backup.skill", SkillStatus.DISABLED)
            admin.restore(backup, authorized=True)
            self.assertEqual(registry.get("backup.skill").status, SkillStatus.ACTIVE)


if __name__ == "__main__":
    unittest.main()
