"""Tests for immutable versioned agent definitions."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.mcp.platform.agent_definitions import (
    AgentDefinition,
    AgentDefinitionConflict,
    AgentDefinitionStore,
)


class TestAgentDefinitions(unittest.TestCase):
    def test_register_is_idempotent_for_same_version_and_digest(self) -> None:
        store = AgentDefinitionStore()
        try:
            definition = AgentDefinition(
                agent_id="researcher",
                version="1.0.0",
                model_strategy={"mode": "capability_first", "model": "qwen2.5:3b"},
                instructions="Research carefully.",
                skill_ids=("search",),
                tool_ids=("browser.search",),
                privacy_class="private",
                max_subagents=2,
            )
            first = store.register(definition)
            second = store.register(definition)
            self.assertEqual(first.digest, definition.digest)
            self.assertEqual(second.to_dict(), first.to_dict())
            self.assertEqual(store.get("researcher", "1.0.0").digest, definition.digest)
        finally:
            store.close()

    def test_same_version_cannot_change_definition(self) -> None:
        store = AgentDefinitionStore()
        try:
            store.register(AgentDefinition("researcher", "1", {}, "one"))
            with self.assertRaises(AgentDefinitionConflict):
                store.register(AgentDefinition("researcher", "1", {}, "changed"))
            self.assertEqual(len(store.list_versions("researcher")), 1)
        finally:
            store.close()

    def test_versions_are_append_only_and_survive_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "definitions.sqlite3"
            first = AgentDefinitionStore(database)
            first.register(AgentDefinition("researcher", "1", {}, "one"))
            first.register(AgentDefinition("researcher", "2", {}, "two"))
            first.close()
            reopened = AgentDefinitionStore(database)
            try:
                self.assertEqual(
                    [item.definition.version for item in reopened.list_versions("researcher")],
                    ["1", "2"],
                )
            finally:
                reopened.close()

    def test_definition_limits_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            AgentDefinition("", "1", {}, "x")
        with self.assertRaises(ValueError):
            AgentDefinition("agent", "1", {}, "x", max_subagents=33)


if __name__ == "__main__":
    unittest.main()
