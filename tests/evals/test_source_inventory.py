"""Structural inventory assertions only; live inventory remains a separate gate."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class SourceInventoryTests(unittest.TestCase):
    def test_inventory_does_not_claim_runtime_or_live_capabilities(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HERE / "source_inventory.py")],
            capture_output=True, text=True, check=False, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(result.stdout)
        self.assertFalse(snapshot["mcp_connections_tested"])
        self.assertIsNone(snapshot["runtime_models"])
        self.assertIsNone(snapshot["authenticated_active_endpoints"])
        self.assertEqual(snapshot["production_deployment"], "NOT_VERIFIED")
        self.assertFalse(snapshot["private_policy_values_included"])
        self.assertGreater(len(snapshot["tool_inventory"]), 20)
        self.assertEqual(snapshot["mcp_server_ids_declared"], [])
        self.assertIn("COMPUTEMESH_AGENTS_PLATFORM_ENABLED", snapshot["environment_flags_declared"])

    def test_source_tool_rows_have_unique_evidence_locations(self) -> None:
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("source_inventory", HERE / "source_inventory.py")
        assert spec is not None and spec.loader is not None
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        records = module.declared_tools()
        self.assertEqual(len(records), len({(row["name"], row["line"]) for row in records}))
        self.assertTrue(all(row["lifecycle"] == "SOURCE_DECLARED_ONLY" for row in records))
        self.assertIn("search_web", {row["name"] for row in records})


if __name__ == "__main__":
    unittest.main()
