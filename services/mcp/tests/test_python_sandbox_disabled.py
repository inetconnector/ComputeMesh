"""P0: the former Python sandbox must never run code inside the MCP server."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.builtin import python_sandbox


class TestUnsafePythonInterpreterDisabled(unittest.TestCase):
    def test_all_legacy_entry_points_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "would-be-execution.txt"
            payload = (
                "from pathlib import Path\n"
                + f"Path({str(marker)!r}).write_text('UNSAFE', encoding='utf-8')\n"
                + "result = 'executed'\n"
            )
            for executor in (
                python_sandbox.execute_python_code,
                python_sandbox.run_code_interpreter,
            ):
                for store_state in (True, False):
                    with self.subTest(executor=executor.__name__, store_state=store_state):
                        reply = executor(payload, timeout_seconds=0.01, store_state=store_state)
                        self.assertIs(reply["success"], False)
                        self.assertEqual(reply["status"], "disabled")
                        self.assertEqual(reply["stdout"], "")
                        self.assertEqual(reply["stderr"], "")
                        self.assertIsNone(reply["result"])
                        self.assertEqual(reply["images"], [])
                        self.assertIn("disabled", reply["error"])
                        self.assertFalse(marker.exists())

    def test_even_benign_code_and_aliases_cannot_bypass_disablement(self) -> None:
        self.assertIs(
            python_sandbox.run_code_interpreter,
            python_sandbox.execute_python_code,
        )
        for code in ("1 + 1", "print('hello')", "", "import os", "while True: pass"):
            with self.subTest(code=code):
                result = python_sandbox.execute_python_code(code)
                self.assertFalse(result["success"])
                self.assertEqual(result["status"], "disabled")
                self.assertNotIn("hello", result["stdout"])


if __name__ == "__main__":
    unittest.main()
