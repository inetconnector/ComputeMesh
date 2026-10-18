"""Static, non-executing tool/config snapshot for capability baseline.

Source-declared != enabled, authorized, installed or live. This intentionally
does not import ToolRegistry, initialize integrations or enumerate secrets.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "services/mcp/tool_registry.py"
CONFIG = ROOT / "services/mcp/config.py"
MCP_SERVERS = ROOT / "services/mcp/mcp_config.json"
GATEWAY = ROOT / "services/gateway/inference.py"


def _constant(node: ast.AST | None) -> str | bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bool)):
        return node.value
    return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def declared_tools() -> list[dict[str, Any]]:
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "register_tool" or not node.args:
            continue
        name = _constant(node.args[0])
        if not isinstance(name, str):
            continue
        options = {kw.arg: _constant(kw.value) for kw in node.keywords if kw.arg}
        tools.append({
            "name": name,
            "source": options.get("source"),
            "owner_only_declared": options.get("owner_only", False),
            "schema_expression": ast.unparse(node.args[2]) if len(node.args) > 2 else None,
            "line": node.lineno,
            "lifecycle": "SOURCE_DECLARED_ONLY",
        })
    return sorted(tools, key=lambda row: (row["name"], row["line"]))


def _git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True,
            text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def snapshot() -> dict[str, Any]:
    server_document = json.loads(MCP_SERVERS.read_text(encoding="utf-8"))
    if not isinstance(server_document, dict):
        raise ValueError("invalid MCP config document")
    configured = server_document.get("mcpServers", {})
    if not isinstance(configured, dict):
        raise ValueError("mcpServers must be object")
    config_text = CONFIG.read_text(encoding="utf-8")
    flags = sorted(set(re.findall(r"COMPUTEMESH_[A-Z0-9_]+", config_text)))
    return {
        "schema_version": 1,
        "source_commit": _git(["rev-parse", "HEAD"]),
        "source_dirty": _git(["status", "--porcelain"]) not in (None, ""),
        "source_sha256": {str(p.relative_to(ROOT)): _sha(p) for p in (REGISTRY, CONFIG, MCP_SERVERS, GATEWAY)},
        "tool_inventory": declared_tools(),
        "tool_inventory_semantics": "Static AST only; tool availability, scopes and schemas require authenticated runtime probe.",
        "environment_flags_declared": flags,
        "mcp_server_ids_declared": sorted(configured.keys()),
        "mcp_connections_tested": False,
        "runtime_models": None,
        "authenticated_active_endpoints": None,
        "staging_deployment": "NOT_VERIFIED",
        "production_deployment": "NOT_VERIFIED",
        "physical_phone": "NOT_VERIFIED",
        "nodeos_hardware": "NOT_VERIFIED",
        "private_policy_values_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    value = json.dumps(snapshot(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(value, encoding="utf-8")
    else:
        print(value, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
