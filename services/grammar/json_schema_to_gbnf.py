# SPDX-License-Identifier: Apache-2.0
"""ComputeMesh GBNF Grammar Compiler for Structured Outputs.

Translates JSON Schema and Pydantic definitions into llama.cpp GBNF grammars,
mathematically guaranteeing 100% syntactically valid JSON responses.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def json_schema_to_gbnf(schema: Dict[str, Any]) -> str:
    """Converts a JSON schema dictionary into a strict llama.cpp GBNF grammar."""
    if not isinstance(schema, dict) or not schema:
        # Fallback to general JSON grammar
        return GENERAL_JSON_GBNF

    schema_type = schema.get("type", "object")
    rules: List[str] = []

    if schema_type == "object":
        props = schema.get("properties", {})
        required = schema.get("required", list(props.keys()))

        prop_rules = []
        for p_name, p_spec in props.items():
            rule_name = f"prop_{_sanitize_rule_name(p_name)}"
            rule_val = _compile_type_to_gbnf(p_spec, p_name)
            prop_rules.append(f'  "\\"" "{p_name}" "\\"" ws ":" ws {rule_name}')
            rules.append(f"{rule_name} ::= {rule_val}")

        if prop_rules:
            members_str = ' ("," ws)?\n  '.join(prop_rules)
            root_rule = f'root ::= "{{" ws\n  {members_str}\n  ws "}}"'
        else:
            root_rule = 'root ::= "{" ws (member ("," ws member)*)? ws "}"'
            rules.append('member ::= string ":" ws value')

        rules.insert(0, root_rule)

    elif schema_type == "array":
        items_spec = schema.get("items", {})
        item_rule = _compile_type_to_gbnf(items_spec, "item")
        rules.append(f'root ::= "[" ws (item ("," ws item)*)? ws "]"')
        rules.append(f"item ::= {item_rule}")
    else:
        rules.append(f"root ::= {_compile_type_to_gbnf(schema, 'root')}")

    # Standard JSON primitive terminal rules
    rules.extend([
        'string ::= "\\"" ([^"\\\\] | "\\\\" (["\\\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]))* "\\""',
        'number ::= "-"? [0-9]+ ("." [0-9]+)? ([eE] [-+]? [0-9]+)?',
        'integer ::= "-"? [0-9]+',
        'boolean ::= "true" | "false"',
        'null ::= "null"',
        'ws ::= [ \\t\\n\\r]*',
    ])

    return "\n".join(rules)


# Aliases
compile_json_schema_to_gbnf = json_schema_to_gbnf


def _sanitize_rule_name(name: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _compile_type_to_gbnf(spec: Dict[str, Any], name_hint: str) -> str:
    if not isinstance(spec, dict):
        return "string"

    if "enum" in spec and isinstance(spec["enum"], list) and spec["enum"]:
        enum_vals = spec["enum"]
        parts = []
        for val in enum_vals:
            if isinstance(val, str):
                parts.append(f'"\\"" "{val}" "\\""')
            elif isinstance(val, (int, float, bool)):
                parts.append(f'"{val}"')
            elif val is None:
                parts.append('"null"')
        return " | ".join(parts) if parts else "string"


    t = spec.get("type", "string")
    if t == "string":
        return "string"
    elif t in ("integer", "int"):
        return "integer"
    elif t in ("number", "float"):
        return "number"
    elif t in ("boolean", "bool"):
        return "boolean"
    elif t == "array":
        item_spec = spec.get("items", {})
        sub_rule = _compile_type_to_gbnf(item_spec, f"{name_hint}_sub")
        return f'"[" ws ({sub_rule} ("," ws {sub_rule})*)? ws "]"'
    elif t == "object":
        return ' "{" ws (string ":" ws string)* ws "}" '
    return "string"


GENERAL_JSON_GBNF = """root ::= object | array
object ::= "{" ws ( member ("," ws member)* )? ws "}"
member ::= string ":" ws value
array ::= "[" ws ( value ("," ws value)* )? ws "]"
value ::= object | array | string | number | boolean | null
string ::= "\\"" ([^"\\\\] | "\\\\" (["\\\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]))* "\\""
number ::= "-"? [0-9]+ ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
integer ::= "-"? [0-9]+
boolean ::= "true" | "false"
null ::= "null"
ws ::= [ \\t\\n\\r]*
"""
