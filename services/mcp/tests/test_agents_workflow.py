"""Contract tests for the resumable Agents Platform DAG workflow engine."""
from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

from services.mcp.platform.workflow import (
    DAGWorkflowEngine,
    WorkflowDefinitionError,
    WorkflowNode,
    WorkflowStateConflict,
)


class TestAgentsWorkflow(unittest.TestCase):
    def test_dependency_order_and_resume_skip_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = DAGWorkflowEngine(Path(directory) / "workflow.sqlite3")
            try:
                nodes = (
                    WorkflowNode("a", "first"),
                    WorkflowNode("b", "second", dependencies=("a",)),
                )
                calls: list[str] = []

                def runner(node: WorkflowNode) -> dict[str, str]:
                    calls.append(node.node_id)
                    return {"node": node.node_id}

                first = engine.execute("wf-1", nodes, runner)
                self.assertEqual(first.status, "COMPLETED")
                self.assertEqual(calls, ["a", "b"])
                second = engine.execute("wf-1", nodes, runner)
                self.assertEqual(second.status, "COMPLETED")
                self.assertTrue(second.resumed)
                self.assertEqual(calls, ["a", "b"])
            finally:
                engine.close()

    def test_independent_nodes_may_execute_in_parallel(self) -> None:
        engine = DAGWorkflowEngine()
        nodes = (
            WorkflowNode("a", "parallel a"),
            WorkflowNode("b", "parallel b"),
        )
        barrier = threading.Barrier(2, timeout=2)

        def runner(node: WorkflowNode) -> str:
            barrier.wait()
            return node.node_id

        result = engine.execute("wf-parallel", nodes, runner, max_workers=2)
        self.assertEqual(result.status, "COMPLETED")

    def test_failure_blocks_dependents_without_fake_success(self) -> None:
        engine = DAGWorkflowEngine()
        nodes = (
            WorkflowNode("a", "fails", max_attempts=2),
            WorkflowNode("b", "dependent", dependencies=("a",)),
        )
        attempts = 0

        def runner(node: WorkflowNode) -> str:
            nonlocal attempts
            if node.node_id == "a":
                attempts += 1
                raise RuntimeError("down")
            return "must-not-run"

        result = engine.execute("wf-failure", nodes, runner)
        by_id = {node.node_id: node for node in result.nodes}
        self.assertEqual(result.status, "PARTIAL_FAILURE")
        self.assertEqual(by_id["a"].status, "FAILED")
        self.assertEqual(by_id["a"].attempts, 2)
        self.assertEqual(by_id["b"].status, "BLOCKED")
        self.assertEqual(attempts, 2)

    def test_explicit_reset_allows_controlled_retry(self) -> None:
        engine = DAGWorkflowEngine()
        node = WorkflowNode("a", "retry later", max_attempts=1)
        fail = True

        def runner(_: WorkflowNode) -> str:
            if fail:
                raise RuntimeError("transient")
            return "ok"

        first = engine.execute("wf-reset", (node,), runner)
        self.assertEqual(first.status, "PARTIAL_FAILURE")
        self.assertEqual(engine.reset_failed("wf-reset"), 1)
        fail = False
        second = engine.execute("wf-reset", (node,), runner)
        self.assertEqual(second.status, "COMPLETED")

    def test_definition_change_under_same_id_is_rejected(self) -> None:
        engine = DAGWorkflowEngine()
        engine.execute("wf-stable", (WorkflowNode("a", "one"),), lambda _: "ok")
        with self.assertRaises(WorkflowStateConflict):
            engine.execute("wf-stable", (WorkflowNode("a", "changed"),), lambda _: "ok")

    def test_cycle_and_missing_dependency_are_rejected(self) -> None:
        with self.assertRaises(WorkflowDefinitionError):
            DAGWorkflowEngine.validate_dag(
                (
                    WorkflowNode("a", "a", dependencies=("b",)),
                    WorkflowNode("b", "b", dependencies=("a",)),
                )
            )
        with self.assertRaises(WorkflowDefinitionError):
            DAGWorkflowEngine.validate_dag((WorkflowNode("a", "a", dependencies=("missing",)),))

    def test_result_validation_failure_is_structured(self) -> None:
        engine = DAGWorkflowEngine()
        result = engine.execute(
            "wf-validation",
            (WorkflowNode("a", "validate"),),
            lambda _: {"value": 1},
            validators={"a": lambda value: value.get("value") == 2},
        )
        self.assertEqual(result.status, "PARTIAL_FAILURE")
        self.assertIn("validation failed", result.nodes[0].error)

    def test_same_workflow_cannot_execute_twice_concurrently_in_process(self) -> None:
        engine = DAGWorkflowEngine()
        entered = threading.Event()
        release = threading.Event()
        errors: list[Exception] = []

        def runner(_: WorkflowNode) -> str:
            entered.set()
            release.wait(timeout=2)
            return "ok"

        def first_run() -> None:
            engine.execute("wf-lock", (WorkflowNode("a", "hold"),), runner)

        thread = threading.Thread(target=first_run)
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        try:
            engine.execute("wf-lock", (WorkflowNode("a", "hold"),), lambda _: "duplicate")
        except Exception as exc:
            errors.append(exc)
        release.set()
        thread.join(timeout=2)
        self.assertTrue(errors)
        self.assertIsInstance(errors[0], WorkflowStateConflict)

    def test_interrupted_running_state_respects_attempt_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "workflow.sqlite3"
            engine = DAGWorkflowEngine(db)
            node = WorkflowNode("a", "interrupted", max_attempts=2)
            engine._ensure_workflow("wf-interrupt", (node,))
            engine._set_running("wf-interrupt", "a", 1)
            engine.close()
            resumed = DAGWorkflowEngine(db)
            try:
                calls = 0

                def runner(_: WorkflowNode) -> str:
                    nonlocal calls
                    calls += 1
                    return "recovered"

                result = resumed.execute("wf-interrupt", (node,), runner)
                self.assertEqual(result.status, "COMPLETED")
                self.assertEqual(calls, 1)
                self.assertEqual(result.nodes[0].attempts, 2)
            finally:
                resumed.close()


if __name__ == "__main__":
    unittest.main()
