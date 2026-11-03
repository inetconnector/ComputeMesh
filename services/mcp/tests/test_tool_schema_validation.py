"""Tests for recursive JSON-schema tool argument validation in ToolRegistry."""
from __future__ import annotations

import unittest

from services.mcp.tool_registry import ToolRegistry, _validate_strict_arguments


class TestToolSchemaValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()

    def test_top_level_arguments_must_be_dict(self) -> None:
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        self.assertIn("JSON-Objekt", _validate_strict_arguments(schema, "not-a-dict"))
        self.assertIn("JSON-Objekt", _validate_strict_arguments(schema, [1, 2]))

    def test_strict_rejects_unknown_properties(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        err = _validate_strict_arguments(schema, {"name": "alice", "extra": 123})
        self.assertIsNotNone(err)
        self.assertIn("Unbekannte Parameter", err)

    def test_strict_rejects_missing_required(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        err = _validate_strict_arguments(schema, {})
        self.assertIsNotNone(err)
        self.assertIn("Fehlende Pflichtparameter", err)

    def test_recursive_nested_object_validation(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "config": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "port": {"type": "integer", "minimum": 1024, "maximum": 65535},
                        "host": {"type": "string", "minLength": 1},
                    },
                    "required": ["port", "host"],
                }
            },
            "required": ["config"],
        }
        # Valid
        self.assertIsNone(_validate_strict_arguments(schema, {"config": {"port": 8080, "host": "localhost"}}))

        # Port out of bounds
        err_min = _validate_strict_arguments(schema, {"config": {"port": 80, "host": "localhost"}})
        self.assertIsNotNone(err_min)
        self.assertIn("unter dem Minimum", err_min)

        # Port wrong type
        err_type = _validate_strict_arguments(schema, {"config": {"port": "8080", "host": "localhost"}})
        self.assertIsNotNone(err_type)
        self.assertIn("ungültigen Typ", err_type)

        # Nested unknown parameter
        err_extra = _validate_strict_arguments(schema, {"config": {"port": 8080, "host": "localhost", "foo": 1}})
        self.assertIsNotNone(err_extra)
        self.assertIn("Unbekannte Parameter", err_extra)

    def test_nested_array_items_validation(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 10},
                }
            },
        }
        self.assertIsNone(_validate_strict_arguments(schema, {"tags": ["short", "tag"]}))
        err = _validate_strict_arguments(schema, {"tags": ["short", "this-is-too-long-tag"]})
        self.assertIsNotNone(err)
        self.assertIn("überschreitet die Maximallänge", err)


if __name__ == "__main__":
    unittest.main()
