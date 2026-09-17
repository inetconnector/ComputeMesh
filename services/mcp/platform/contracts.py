"""Shared contracts for the ComputeMesh Agents Platform.

These structures are intentionally dependency-light so the public runtime can be
used without importing private ControlPlane policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
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
        request_id: str | None = None,
    ) -> "RequestEnvelope":
        raw = str(text or "")
        normalized = " ".join(raw.casefold().split())
        if isinstance(explicit_skill, str):
            selected = (explicit_skill,) if explicit_skill.strip() else ()
        else:
            selected = tuple(str(item).strip() for item in (explicit_skill or ()) if str(item).strip())
        language = "de" if re.search(r"\b(der|die|das|und|bitte|erstelle|suche|analysiere|prüfe)\b", normalized) else "und"
        clean_request_id = str(request_id or "").strip() or f"req_{uuid.uuid4().hex}"
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,160}", clean_request_id):
            raise ValueError("invalid request_id")
        return cls(
            request_id=clean_request_id,
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
class RuntimePolicyEnvelope:
    """Generic, minimized policy decision accepted by the public runtime.

    Private policy engines may create this contract, but private scoring inputs,
    commercial state and policy internals must never be embedded in it.
    """

    decision_id: str
    request_id: str
    allow_agents: bool
    principal_id: str = ""
    fleet_id: str = ""
    allowed_skills: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    max_side_effect: SideEffectLevel = SideEffectLevel.READ
    privacy_level: str = "default"
    context_budget: int | None = None
    cost_budget: str | None = None
    expires_at: float = 0.0
    policy_version: str = "1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RuntimePolicyEnvelope":
        return cls(
            decision_id=str(value.get("decision_id") or ""),
            request_id=str(value.get("request_id") or ""),
            allow_agents=bool(value.get("allow_agents", False)),
            principal_id=str(value.get("principal_id") or value.get("owner_id") or ""),
            fleet_id=str(value.get("fleet_id") or ""),
            allowed_skills=tuple(str(x) for x in (value.get("allowed_skills") or ())),
            allowed_tools=tuple(str(x) for x in (value.get("allowed_tools") or ())),
            max_side_effect=SideEffectLevel(str(value.get("max_side_effect") or "READ").upper()),
            privacy_level=str(value.get("privacy_level") or "default"),
            context_budget=None if value.get("context_budget") is None else int(value.get("context_budget")),
            cost_budget=None if value.get("cost_budget") is None else str(value.get("cost_budget")),
            expires_at=float(value.get("expires_at") or 0.0),
            policy_version=str(value.get("policy_version") or "1"),
        )

    def validate(
        self,
        *,
        request_id: str,
        principal_id: str | None = None,
        fleet_id: str | None = None,
        now: float | None = None,
    ) -> None:
        timestamp = time.time() if now is None else float(now)
        if not self.decision_id:
            raise PermissionError("runtime policy decision_id is required")
        if self.request_id != request_id:
            raise PermissionError("runtime policy is bound to a different request")
        if self.expires_at <= timestamp:
            raise PermissionError("runtime policy decision expired")
        if principal_id is not None and self.principal_id and self.principal_id != str(principal_id):
            raise PermissionError("runtime policy principal binding mismatch")
        if fleet_id is not None and self.fleet_id and self.fleet_id != str(fleet_id):
            raise PermissionError("runtime policy fleet binding mismatch")
        if not self.allow_agents:
            raise PermissionError("runtime policy denied agents execution")


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
class ToolAuthorizationGrant:
    """Server-side authorization/confirmation bound to one exact tool call."""

    tool_id: str
    request_id: str
    arguments_hash: str
    authorized: bool = False
    confirmed: bool = False
    idempotency_key: str | None = None
    allowed_permissions: tuple[str, ...] = ()
    expires_at: float = 0.0

    @staticmethod
    def hash_arguments(arguments: Mapping[str, Any]) -> str:
        raw = json.dumps(dict(arguments), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def issue(
        cls,
        tool_id: str,
        request_id: str,
        arguments: Mapping[str, Any],
        *,
        authorized: bool,
        confirmed: bool,
        idempotency_key: str | None = None,
        allowed_permissions: Sequence[str] = (),
        ttl_seconds: float = 300.0,
    ) -> "ToolAuthorizationGrant":
        return cls(
            tool_id=str(tool_id),
            request_id=str(request_id),
            arguments_hash=cls.hash_arguments(arguments),
            authorized=bool(authorized),
            confirmed=bool(confirmed),
            idempotency_key=idempotency_key,
            allowed_permissions=tuple(str(x) for x in allowed_permissions),
            expires_at=time.time() + min(max(float(ttl_seconds), 1.0), 3600.0),
        )

    def validate(self, *, tool_id: str, request_id: str | None, arguments: Mapping[str, Any], now: float | None = None) -> None:
        timestamp = time.time() if now is None else float(now)
        if self.tool_id != tool_id:
            raise PermissionError("tool authorization grant tool mismatch")
        if self.request_id != str(request_id or ""):
            raise PermissionError("tool authorization grant request mismatch")
        if self.expires_at <= timestamp:
            raise PermissionError("tool authorization grant expired")
        if self.arguments_hash != self.hash_arguments(arguments):
            raise PermissionError("tool authorization grant arguments mismatch")


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