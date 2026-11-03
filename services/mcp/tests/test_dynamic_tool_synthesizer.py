# SPDX-License-Identifier: Apache-2.0
"""Regression and contract tests for the Autonomous Dynamic Tool Synthesizer.

Verifies the Zero-Trust 7-Layer Quality Gate:
1. Rejection of fake successes and dummy echo fallbacks when no LLM is configured.
2. Rejection of empty 'pass' stubs and trivial echo mock stubs in AST visitor.
3. Strict enforcement of forbidden modules, builtins, and dunder attributes.
4. Preflight smoke test enforcement (no empty or fake return payloads).
5. Safe sandboxed execution of valid computational code.
6. Proper fail-closed error reporting with status='failed' and quality_class='F'.
"""

from __future__ import annotations

import unittest
from typing import Any

from services.mcp.dynamic.ast_security_guard import (
    SecurityASTViolation,
    validate_python_code_ast,
)
from services.mcp.dynamic.synthesizer import (
    DynamicSynthesisError,
    DynamicToolEngine,
)
from services.mcp.tool_registry import ToolRegistry


class TestDynamicToolSynthesizerQualityGate(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DynamicToolEngine()

    def test_synthesis_without_llm_fails_closed(self) -> None:
        """Calling synthesize_tool_code without an LLM caller must refuse fake success."""
        with self.assertRaises(DynamicSynthesisError) as ctx:
            self.engine.synthesize_tool_code("Berechne Primzahlen bis 100", {"n": 100}, llm_caller=None)
        self.assertIn("DYNAMIC_SYNTHESIS_UNAVAILABLE", str(ctx.exception))
        self.assertIn("Scheinerfolg verweigert", str(ctx.exception))

    def test_execution_without_llm_or_code_returns_failed_status(self) -> None:
        """Executing a dynamic task without code or LLM must return status='failed' and quality_class='F'."""
        result = self.engine.execute_dynamic_task(
            task_description="Matrixmultiplikation durchführen",
            inputs={"matrix_a": [[1, 2], [3, 4]], "matrix_b": [[5, 6], [7, 8]]},
            llm_caller=None,
            provided_code=None,
        )
        self.assertEqual(result.get("status"), "failed")
        self.assertIn("DYNAMIC_SYNTHESIS_UNAVAILABLE", result.get("error", ""))
        self.assertEqual(result.get("_dynamic_meta", {}).get("quality_class"), "F")
        self.assertEqual(result.get("_dynamic_meta", {}).get("status"), "rejected_unsafe")

    def test_ast_rejects_empty_pass_stub(self) -> None:
        """AST security guard must reject empty function stubs."""
        code = "def execute(inputs: dict) -> dict:\n    pass\n"
        with self.assertRaises(SecurityASTViolation) as ctx:
            validate_python_code_ast(code)
        self.assertIn("Leere Methodenrümpfe", str(ctx.exception))

    def test_ast_rejects_trivial_echo_mock_stub(self) -> None:
        """AST security guard must reject trivial echo functions that only return inputs and success."""
        code = (
            "def execute(inputs: dict) -> dict:\n"
            "    # Fake mock\n"
            "    return {'status': 'success', 'inputs': inputs, 'message': 'Dynamisches Tool ausgeführt'}\n"
        )
        with self.assertRaises(SecurityASTViolation) as ctx:
            validate_python_code_ast(code)
        self.assertIn("Triviale Echo- oder Mock-Funktionen", str(ctx.exception))

    def test_ast_rejects_forbidden_modules(self) -> None:
        """Code importing unapproved modules like os, sys, or subprocess must be rejected."""
        forbidden_snippets = [
            "import os\ndef execute(inputs: dict) -> dict:\n    return {'out': os.getcwd()}\n",
            "import subprocess\ndef execute(inputs: dict) -> dict:\n    return {'out': 1}\n",
            "import sys\ndef execute(inputs: dict) -> dict:\n    return {'out': sys.version}\n",
        ]
        for snippet in forbidden_snippets:
            with self.subTest(snippet=snippet), self.assertRaises(SecurityASTViolation):
                validate_python_code_ast(snippet)

    def test_ast_rejects_dangerous_builtins_and_dunders(self) -> None:
        """Code using eval, exec, open or dunder escape must be rejected."""
        bad_snippets = [
            "def execute(inputs: dict) -> dict:\n    eval('1+1')\n    return {'r': 2}\n",
            "def execute(inputs: dict) -> dict:\n    open('/etc/passwd')\n    return {'r': 2}\n",
            "def execute(inputs: dict) -> dict:\n    c = ().__class__.__bases__[0]\n    return {'r': str(c)}\n",
        ]
        for snippet in bad_snippets:
            with self.subTest(snippet=snippet), self.assertRaises(SecurityASTViolation):
                validate_python_code_ast(snippet)

    def test_preflight_smoke_test_rejects_trivial_echo(self) -> None:
        """Smoke test must reject return values that are only status=success without computation."""
        from services.mcp.dynamic.sandbox_runner import SandboxExecutionError
        code = (
            "def execute(inputs: dict) -> dict:\n"
            "    x = 1 + 1\n"
            "    return {'status': 'success', 'inputs': inputs}\n"
        )
        with self.assertRaises(SandboxExecutionError) as ctx:
            self.engine.preflight_smoke_test(code, {"a": 1})
        self.assertIn("Trivialer Scheinerfolg", str(ctx.exception))

    def test_valid_computational_code_executes_successfully(self) -> None:
        """Valid, non-mock mathematical calculation code executes and returns verified result."""
        code = (
            "def execute(inputs: dict) -> dict:\n"
            "    n = int(inputs.get('n', 5))\n"
            "    # Compute factorial\n"
            "    fact = 1\n"
            "    for i in range(1, n + 1):\n"
            "        fact *= i\n"
            "    return {'factorial': fact, 'n': n, 'status': 'success'}\n"
        )
        result = self.engine.execute_dynamic_task(
            task_description="Berechne die Fakultät einer Ganzzahl",
            inputs={"n": 6},
            provided_code=code,
        )
        self.assertEqual(result.get("factorial"), 720)
        self.assertEqual(result.get("n"), 6)
        self.assertEqual(result.get("_dynamic_meta", {}).get("status"), "verified_safe")
        self.assertEqual(result.get("_dynamic_meta", {}).get("attempts"), 1)

    def test_simulated_llm_caller_synthesis_flow(self) -> None:
        """When an LLM caller is supplied, valid synthesized code is executed properly."""
        valid_generated_code = (
            "def execute(inputs: dict) -> dict:\n"
            "    nums = inputs.get('numbers', [])\n"
            "    squared = [x * x for x in nums]\n"
            "    return {'squared': squared, 'count': len(squared)}\n"
        )

        def mock_llm_caller(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "choices": [{
                    "message": {
                        "content": f"```python\n{valid_generated_code}\n```"
                    }
                }]
            }

        result = self.engine.execute_dynamic_task(
            task_description="Quadriere alle Zahlen in der Liste",
            inputs={"numbers": [1, 2, 3, 4, 5]},
            llm_caller=mock_llm_caller,
        )
        self.assertEqual(result.get("squared"), [1, 4, 9, 16, 25])
        self.assertEqual(result.get("count"), 5)
        self.assertEqual(result.get("_dynamic_meta", {}).get("status"), "verified_safe")

    def test_tool_registry_integration_fails_closed_when_no_code_and_no_llm(self) -> None:
        """The tool registry wrapper for dynamic_compute_tool must fail closed without LLM."""
        registry = ToolRegistry()
        res = registry.execute_tool(
            "dynamic_compute_tool",
            {"task_description": "Generiere einen Zufalls-Graph"},
        )
        self.assertEqual(res.get("status"), "failed")
        self.assertIn("DYNAMIC_SYNTHESIS_UNAVAILABLE", res.get("error", ""))


if __name__ == "__main__":
    unittest.main()

