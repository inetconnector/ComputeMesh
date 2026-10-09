"""Immutable, versioned agent-definition registry.

Definitions are configuration contracts, not mutable runtime state. A session
may keep using the exact version it started with while a newer version is
registered for future sessions.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class AgentDefinitionError(ValueError):
    """Raised when an agent definition is invalid or conflicts with history."""


class AgentDefinitionConflict(AgentDefinitionError):
    """Raised when an existing agent/version has different immutable content."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bounded_strings(name: str, values: Sequence[str], *, limit: int = 128) -> tuple[str, ...]:
    if len(values) > 100:
        raise AgentDefinitionError(f"{name} cannot contain more than 100 entries")
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not 1 <= len(clean) <= limit:
            raise AgentDefinitionError(f"{name} entries must be between 1 and {limit} characters")
        result.append(clean)
    return tuple(dict.fromkeys(result))


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    version: str
    model_strategy: Mapping[str, Any]
    instructions: str
    skill_ids: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    mcp_server_ids: tuple[str, ...] = ()
    allowed_node_ids: tuple[str, ...] = ()
    privacy_class: str = "private"
    budget_class: str = "standard"
    max_subagents: int = 0
    approval_classes: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    network_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        agent_id = str(self.agent_id or "").strip()
        version = str(self.version or "").strip()
        instructions = str(self.instructions or "")
        if not 1 <= len(agent_id) <= 128 or not 1 <= len(version) <= 64:
            raise AgentDefinitionError("agent_id/version has an invalid length")
        if len(instructions) > 32_768:
            raise AgentDefinitionError("instructions must be at most 32768 characters")
        if not isinstance(self.model_strategy, Mapping):
            raise AgentDefinitionError("model_strategy must be a mapping")
        if self.privacy_class not in {"public", "private", "confidential"}:
            raise AgentDefinitionError("unsupported privacy_class")
        if not 0 <= int(self.max_subagents) <= 32:
            raise AgentDefinitionError("max_subagents must be between 0 and 32")
        for name in (
            "skill_ids", "tool_ids", "mcp_server_ids", "allowed_node_ids",
            "approval_classes", "allowed_paths", "network_allowlist",
        ):
            _bounded_strings(name, getattr(self, name))

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict(include_digest=False)).encode("utf-8")).hexdigest()

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "agent_id": str(self.agent_id).strip(),
            "version": str(self.version).strip(),
            "model_strategy": dict(self.model_strategy),
            "instructions": str(self.instructions),
            "skill_ids": list(_bounded_strings("skill_ids", self.skill_ids)),
            "tool_ids": list(_bounded_strings("tool_ids", self.tool_ids)),
            "mcp_server_ids": list(_bounded_strings("mcp_server_ids", self.mcp_server_ids)),
            "allowed_node_ids": list(_bounded_strings("allowed_node_ids", self.allowed_node_ids)),
            "privacy_class": str(self.privacy_class),
            "budget_class": str(self.budget_class),
            "max_subagents": int(self.max_subagents),
            "approval_classes": list(_bounded_strings("approval_classes", self.approval_classes)),
            "allowed_paths": list(_bounded_strings("allowed_paths", self.allowed_paths)),
            "network_allowlist": list(_bounded_strings("network_allowlist", self.network_allowlist)),
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload


@dataclass(frozen=True)
class RegisteredAgentDefinition:
    definition: AgentDefinition
    created_at: float

    @property
    def digest(self) -> str:
        return self.definition.digest

    def to_dict(self) -> dict[str, Any]:
        payload = self.definition.to_dict()
        payload["created_at"] = self.created_at
        return payload


class AgentDefinitionStore:
    """SQLite-backed append-only registry keyed by agent ID and version."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 30000")
        if str(path) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS agent_definitions (
                agent_id TEXT NOT NULL,
                version TEXT NOT NULL,
                digest TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(agent_id, version)
            )"""
        )
        self._connection.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> RegisteredAgentDefinition:
        payload = json.loads(str(row["payload_json"]))
        definition = AgentDefinition(
            agent_id=payload["agent_id"],
            version=payload["version"],
            model_strategy=payload["model_strategy"],
            instructions=payload["instructions"],
            skill_ids=tuple(payload.get("skill_ids", ())),
            tool_ids=tuple(payload.get("tool_ids", ())),
            mcp_server_ids=tuple(payload.get("mcp_server_ids", ())),
            allowed_node_ids=tuple(payload.get("allowed_node_ids", ())),
            privacy_class=payload.get("privacy_class", "private"),
            budget_class=payload.get("budget_class", "standard"),
            max_subagents=int(payload.get("max_subagents", 0)),
            approval_classes=tuple(payload.get("approval_classes", ())),
            allowed_paths=tuple(payload.get("allowed_paths", ())),
            network_allowlist=tuple(payload.get("network_allowlist", ())),
        )
        if definition.digest != str(row["digest"]):
            raise AgentDefinitionConflict("stored agent definition digest does not verify")
        return RegisteredAgentDefinition(definition, float(row["created_at"]))

    def register(self, definition: AgentDefinition) -> RegisteredAgentDefinition:
        if not isinstance(definition, AgentDefinition):
            raise TypeError("definition must be an AgentDefinition")
        payload = definition.to_dict(include_digest=False)
        digest = definition.digest
        agent_id = str(definition.agent_id).strip()
        version = str(definition.version).strip()
        with self._lock:
            existing = self._connection.execute(
                "SELECT * FROM agent_definitions WHERE agent_id = ? AND version = ?",
                (agent_id, version),
            ).fetchone()
            if existing is not None:
                if str(existing["digest"]) != digest:
                    raise AgentDefinitionConflict(
                        f"agent definition already exists: {definition.agent_id}@{definition.version}"
                    )
                return self._row(existing)
            created_at = time.time()
            self._connection.execute(
                """INSERT INTO agent_definitions(agent_id, version, digest, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (agent_id, version, digest, _canonical(payload), created_at),
            )
            self._connection.commit()
            return RegisteredAgentDefinition(definition, created_at)

    def get(self, agent_id: str, version: str) -> RegisteredAgentDefinition:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM agent_definitions WHERE agent_id = ? AND version = ?",
                (str(agent_id).strip(), str(version).strip()),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown agent definition: {agent_id}@{version}")
        return self._row(row)

    def list_versions(self, agent_id: str) -> tuple[RegisteredAgentDefinition, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM agent_definitions WHERE agent_id = ? ORDER BY created_at ASC, version ASC",
                (str(agent_id).strip(),),
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()
