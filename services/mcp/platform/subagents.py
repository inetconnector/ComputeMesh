"""Formal subagent delegation contracts and scope validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid


@dataclass(frozen=True)
class SubagentContract:
    contract_id: str
    task: str
    allowed_paths: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    expected_output: str
    return_schema: Mapping[str, Any] = field(default_factory=dict)
    stop_conditions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    max_steps: int = 20
    context_refs: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        task: str,
        *,
        allowed_paths: Sequence[str] = (),
        allowed_tools: Sequence[str] = (),
        expected_output: str,
        return_schema: Mapping[str, Any] | None = None,
        stop_conditions: Sequence[str] = (),
        forbidden_actions: Sequence[str] = (),
        max_steps: int = 20,
        context_refs: Sequence[str] = (),
    ) -> "SubagentContract":
        clean_task = str(task or "").strip()
        if not clean_task:
            raise ValueError("subagent task is required")
        if not str(expected_output or "").strip():
            raise ValueError("expected_output is required")
        if not 1 <= int(max_steps) <= 100:
            raise ValueError("max_steps must be between 1 and 100")
        return cls(
            contract_id=f"sub_{uuid.uuid4().hex}",
            task=clean_task,
            allowed_paths=tuple(str(path) for path in allowed_paths),
            allowed_tools=tuple(str(tool) for tool in allowed_tools),
            expected_output=str(expected_output),
            return_schema=dict(return_schema or {}),
            stop_conditions=tuple(str(item) for item in stop_conditions),
            forbidden_actions=tuple(str(item) for item in forbidden_actions),
            max_steps=int(max_steps),
            context_refs=tuple(str(item) for item in context_refs),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubagentResult:
    contract_id: str
    status: str
    output: Any
    steps_used: int
    tools_used: tuple[str, ...]
    paths_touched: tuple[str, ...]
    errors: tuple[str, ...] = ()


class SubagentGate:
    """Validate delegated operations against the caller-defined contract."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def validate_tool(self, contract: SubagentContract, tool_name: str) -> None:
        if tool_name not in set(contract.allowed_tools):
            raise PermissionError(f"tool not allowed by subagent contract: {tool_name}")

    def validate_path(self, contract: SubagentContract, path: str | Path) -> Path:
        target = Path(path)
        if not target.is_absolute():
            target = self.workspace_root / target
        resolved = target.resolve()
        if resolved != self.workspace_root and self.workspace_root not in resolved.parents:
            raise PermissionError(f"path escapes workspace: {resolved}")
        allowed_roots: list[Path] = []
        for raw in contract.allowed_paths:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = self.workspace_root / candidate
            allowed_roots.append(candidate.resolve())
        if allowed_roots and not any(resolved == root or root in resolved.parents for root in allowed_roots):
            raise PermissionError(f"path outside delegated scope: {resolved}")
        return resolved

    @staticmethod
    def validate_result(contract: SubagentContract, result: SubagentResult) -> None:
        if result.contract_id != contract.contract_id:
            raise ValueError("subagent result does not match contract")
        if result.steps_used > contract.max_steps:
            raise ValueError("subagent exceeded max_steps")
        unauthorized_tools = sorted(set(result.tools_used) - set(contract.allowed_tools))
        if unauthorized_tools:
            raise PermissionError(f"subagent used unauthorized tools: {', '.join(unauthorized_tools)}")
        if result.status == "COMPLETED" and result.errors:
            raise ValueError("completed subagent result cannot contain unresolved errors")

    def validate_result_paths(self, contract: SubagentContract, result: SubagentResult) -> None:
        for path in result.paths_touched:
            self.validate_path(contract, path)
