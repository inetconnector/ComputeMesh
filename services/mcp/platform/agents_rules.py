"""Hierarchical AGENTS.md discovery and scope resolution."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class AgentRuleDocument:
    path: str
    scope: str
    depth: int
    checksum: str
    content: str
    authority: str = "AUTHORIZED_REPOSITORY_INSTRUCTION"


@dataclass(frozen=True)
class RuleResolution:
    workspace_root: str
    target_path: str
    documents: tuple[AgentRuleDocument, ...]

    @property
    def effective_text(self) -> str:
        if not self.documents:
            return ""
        return "\n\n".join(
            f"<!-- AGENTS scope={doc.scope} source={doc.path} -->\n{doc.content.strip()}"
            for doc in self.documents
        )


class AgentsRuleResolver:
    """Resolve root-to-leaf AGENTS.md instructions for a repository path."""

    def __init__(self, workspace_root: str | Path, *, max_file_bytes: int = 256 * 1024) -> None:
        self.root = Path(workspace_root).resolve()
        self.max_file_bytes = max(1, int(max_file_bytes))
        if not self.root.exists():
            raise FileNotFoundError(self.root)

    def _inside_root(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"path escapes workspace root: {resolved}")
        return resolved

    def _rule_at(self, directory: Path) -> AgentRuleDocument | None:
        rule = directory / "AGENTS.md"
        if not rule.is_file():
            return None
        resolved = self._inside_root(rule)
        raw = resolved.read_bytes()
        if len(raw) > self.max_file_bytes:
            raise ValueError(f"AGENTS.md exceeds maximum size: {resolved}")
        if b"\x00" in raw:
            raise ValueError(f"NUL byte in AGENTS.md: {resolved}")
        try:
            content = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError(f"AGENTS.md must be UTF-8: {resolved}") from exc
        rel_dir = directory.relative_to(self.root)
        scope = "." if str(rel_dir) == "." else rel_dir.as_posix()
        return AgentRuleDocument(
            path=str(resolved), scope=scope,
            depth=len(rel_dir.parts) if str(rel_dir) != "." else 0,
            checksum=hashlib.sha256(raw).hexdigest(), content=content,
        )

    def resolve(self, target_path: str | Path) -> RuleResolution:
        candidate = Path(target_path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        target = self._inside_root(candidate)
        directory = target if target.is_dir() else target.parent
        directory = self._inside_root(directory)
        chain: list[Path] = []
        current = directory
        while True:
            chain.append(current)
            if current == self.root:
                break
            current = current.parent
            if self.root not in current.parents and current != self.root:
                raise ValueError("scope traversal escaped workspace root")
        chain.reverse()
        documents = tuple(doc for scoped_dir in chain if (doc := self._rule_at(scoped_dir)) is not None)
        return RuleResolution(str(self.root), str(target), documents)

    def scope_map(self, paths: Sequence[str | Path]) -> dict[str, list[str]]:
        return {str(path): [doc.path for doc in self.resolve(path).documents] for path in paths}
