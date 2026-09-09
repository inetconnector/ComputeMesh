# SPDX-License-Identifier: Apache-2.0
"""Security regression tests for the bounded calculator."""

from __future__ import annotations

import unittest

from services.mcp.builtin.python_calc import run_python_calc


class TestCalculatorHardening(unittest.TestCase):
    def test_loops_are_rejected_before_execution(self):
        result = run_python_calc("while True:\n    pass")
        self.assertIn("Sicherheitsrichtlinie", result["error"])
        self.assertIn("While", result["error"])

    def test_comprehensions_are_rejected(self):
        result = run_python_calc("sum(x for x in range(10))")
        self.assertIn("Sicherheitsrichtlinie", result["error"])
        self.assertIn("GeneratorExp", result["error"])

    def test_unapproved_math_resource_function_is_rejected(self):
        result = run_python_calc("math.factorial(100000000)")
        self.assertIn("nicht freigegeben", result["error"])

    def test_exponent_is_bounded(self):
        result = run_python_calc("10 ** 1000000")
        self.assertIn("Exponent", result["error"])

    def test_dynamic_exponent_is_rejected(self):
        result = run_python_calc("n = 100\nresult = 10 ** n")
        self.assertIn("direkte numerische Konstante", result["error"])

    def test_sequence_bomb_is_rejected(self):
        result = run_python_calc("data = [1]\nresult = data * 100000000")
        self.assertIn("Sequenzmultiplikation", result["error"])


if __name__ == "__main__":
    unittest.main()
