"""Shared contracts for the ComputeMesh Agents Platform.

These structures are intentionally dependency-light so the public runtime can be
used without importing private ControlPlane policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
import time
import uuid
from typing import Any, Mapping, Sequence


class SkillStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPERIMENTAL = "EXPERIMENTAL"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"
    BROKEN = "BROKEN"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SideEffectLevel(str, Enum):
    NONE = "NONE"
    READ = "READ"
    WRITE_REVERSIBLE = "WRITE_REVERSIBLE"
    WRITE_IRREVERSIBLE = "WRITE_IRREVERSIBLE"
    EXECUTE = "EXECUTE"

    @property
    def rank(self) -> int:
        return {
            SideEffectLevel.NONE: 0,
            SideEffectLevel.READ: 1,
            SideEffectLevel.WRITE_REVERSIBLE: 2,
            SideEffectLevel.WRITE_IRREVERSIBLE: 3,
            SideEffectLevel.EXECUTE: 4,
        }[self]


class ToolLifecycle(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXPERIMENTAL = "EXPERIMENTAL"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"
    BROKEN = "BROKEN"


class ToolMode(str, Enum):
    PREVIEW = "PREVIEW"
    CONFIRM = "CONFIRM"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    name: str
    version: str
    description: str
    status: SkillStatus = SkillStatus.ACTIVE
    priority: int = 50
    domains: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    negative_triggers: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    anti_examples: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    required_tools: tuple[str, ...] = ()
    optional_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    fallback_skills: tuple[str, ...] = ()
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE
    risk_level: RiskLevel = RiskLevel.LOW
    estimated_context_tokens: int = 0
    estimated_latency_ms: int = 0
    estimated_cost_class: str = "unknown"
    validation_rules: tuple[str, ...] = ()
    checksum: str = ""
    signature: str | None = None
    location: str = ""
    source: str = "local"
    summary: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,127}", self.skill_id):
            errors.append("invalid skill_id")
        if not self.name.strip():
            errors.append("name is required")
        if not self.version.strip():
            errors.append("version is required")
        if not 0 <= self.priority <= 100:
            errors.append("priority must be between 0 and 100")
        if self.estimated_context_tokens < 0:
            errors.append("estimated_context_tokens must be non-negative")
        if set(self.required_tools) & set(self.forbidden_tools):
            errors.append("a tool cannot be both required and forbidden")
        if self.skill_id in self.dependencies:
            errors.append("skill cannot depend on itself")
        if self.skill_id in self.conflicts_with:
            errors.append("skill cannot conflict with itself")
        return errors

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["risk_level"] = self.risk_level.value
        value["side_effect_level"] = self.side_effect_level.value
        return value


@dataclass(frozen=True)
class RequestEnvelope:
    request_id: str
    raw_text: str
    normalized_text: str
    language: str = "und"
    user_selected_skills: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    referenced_resources: tuple[str, ...] = ()
    requested_output: str = ""
    explicit_constraints: tuple[str, ...] = ()
    implicit_constraints: tuple[str, ...] = ()
    freshness_requirement: str = ""
    privacy_level: str = "default"
    side_effect_intent: SideEffectLevel = SideEffectLevel.NONE
    time_budget_ms: int | None = None
    cost_budget: str | None = None
    context_budget: int | None = None
    conversation_state_ref: str | None = None
    created_at: float = field(default_factory=time.time)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        explicit_skill: str | Sequence[str] | None = None,
        attachments: Sequence[str] = (),
        requested_output: str = "",
        context_budget: int | None = None,
        privacy_level: str = "default",
        side_effect_intent: SideEffectLevel = SideEffectLevel.NONE,
    ) -> "RequestEnvelope":
        raw = str(text or "")
        normalized = " ".join(raw.casefold().split())
        if isinstance(explicit_skill, str):
            selected = (explicit_skill,) if explicit_skill.strip() else ()
        else:
            selected = tuple(str(item).strip() for item in (explicit_skill or ()) if str(item).strip())
        language = "de" if re.search(r"\b(der|die|das|und|bitte|erstelle|suche|analysiere|prüfe)\b", normalized) else "und"
        return cls(
            request_id=f"req_{uuid.uuid4().hex}",
            raw_text=raw,
            normalized_text=normalized,
            language=language,
            user_selected_skills=selected,
            attachments=tuple(str(item) for item in attachments),
            requested_output=requested_output,
            context_budget=context_budget,
            privacy_level=privacy_level,
            side_effect_intent=side_effect_intent,
        )


@dataclass(frozen=True)
class RouteCandidate:
    skill_id: str
    score: float
    priority: int
    signals: tuple[str, ...] = ()
    excluded_reason: str = ""


@dataclass(frozen=True)
class RoutingDecision:
    request_id: str
    status: str
    selected_skills: tuple[str, ...] = ()
    candidates: tuple[RouteCandidate, ...] = ()
    dag_nodes: tuple[str, ...] = ()
    dag_edges: tuple[tuple[str, str], ...] = ()
    reasons: tuple[str, ...] = ()
    requires_user_choice: bool = False
    abstained: bool = False
    context_tokens_estimated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "selected_skills": list(self.selected_skills),
            "candidates": [asdict(item) for item in self.candidates],
            "dag": {"nodes": list(self.dag_nodes), "edges": [list(edge) for edge in self.dag_edges]},
            "reasons": list(self.reasons),
            "requires_user_choice": self.requires_user_choice,
            "abstained": self.abstained,
            "context_tokens_estimated": self.context_tokens_estimated,
        }


@dataclass(frozen=True)
class ToolManifest:
    tool_id: str
    name: str
    version: str = "1.0"
    description: str = ""
    capabilities: tuple[str, ...] = ()
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    lifecycle: ToolLifecycle = ToolLifecycle.AVAILABLE
    side_effect: SideEffectLevel = SideEffectLevel.EXECUTE
    owner_only: bool = False
    permissions: tuple[str, ...] = ()
    confirmation_required: bool = True
    idempotent: bool = False
    reversible: bool = False
    retry_limit: int = 0
    timeout_seconds: float | None = None
    cost_class: str = "unknown"
    latency_class: str = "unknown"
    data_sensitivity: str = "default"
    source: str = "legacy"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["lifecycle"] = self.lifecycle.value
        value["side_effect"] = self.side_effect.value
        return value


@dataclass(frozen=True)
class ToolExecutionContext:
    mode: ToolMode = ToolMode.EXECUTE
    is_owner: bool = False
    authorized: bool = False
    confirmed: bool = False
    owner_id: str | None = None
    idempotency_key: str | None = None
    request_id: str | None = None
    allowed_permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolExecutionResult:
    status: str
    tool_id: str
    mode: ToolMode
    result: Any = None
    error: str = ""
    confirmation_required: bool = False
    idempotency_replay: bool = False
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        return value
