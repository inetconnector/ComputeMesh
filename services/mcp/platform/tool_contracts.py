"""Operational tool result, pagination, resource identity and egress-safety contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import re
import time
from typing import Any, Mapping, Sequence


class ToolResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILURE = "FAILURE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ResourceIdentity:
    resource_type: str
    resource_id: str
    version: str = ""
    uri: str = ""
    etag: str = ""


@dataclass(frozen=True)
class PaginationState:
    next_cursor: str | None = None
    has_more: bool = False
    page: int | None = None
    total_known: int | None = None
    complete: bool = True


@dataclass(frozen=True)
class ToolProvenance:
    tool_id: str
    source: str
    timestamp: float
    version: str = ""
    query: str = ""
    retrieval_mode: str = ""


@dataclass(frozen=True)
class ToolResultEnvelope:
    status: ToolResultStatus
    data: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    provenance: ToolProvenance | None = None
    pagination: PaginationState = field(default_factory=PaginationState)
    resources: tuple[ResourceIdentity, ...] = ()
    side_effect_confirmation: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value

    @property
    def complete(self) -> bool:
        return self.status == ToolResultStatus.SUCCESS and self.pagination.complete and not self.errors


class SecretKind(str, Enum):
    API_KEY = "API_KEY"
    BEARER_TOKEN = "BEARER_TOKEN"
    PRIVATE_KEY = "PRIVATE_KEY"
    PASSWORD_ASSIGNMENT = "PASSWORD_ASSIGNMENT"
    HIGH_ENTROPY_TOKEN = "HIGH_ENTROPY_TOKEN"


@dataclass(frozen=True)
class SecretFinding:
    kind: SecretKind
    location: str
    fingerprint: str


class SecretScanner:
    """Conservative secret detector returning fingerprints, never secret values."""

    _PATTERNS: tuple[tuple[SecretKind, re.Pattern[str]], ...] = (
        (SecretKind.PRIVATE_KEY, re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
        (SecretKind.BEARER_TOKEN, re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*", re.I)),
        (SecretKind.API_KEY, re.compile(r"\b(?:api[_-]?key|token|secret)[\s:=]+[A-Za-z0-9._~+/-]{16,}", re.I)),
        (SecretKind.PASSWORD_ASSIGNMENT, re.compile(r"\b(?:password|passwd|pwd)[\s:=]+[^\s,;]{8,}", re.I)),
    )

    def scan(self, value: Any, *, path: str = "$", max_depth: int = 8) -> list[SecretFinding]:
        findings: list[SecretFinding] = []

        def walk(item: Any, location: str, depth: int) -> None:
            if depth > max_depth:
                return
            if isinstance(item, Mapping):
                for key, nested in item.items():
                    key_text = str(key)
                    nested_location = f"{location}.{key_text}"
                    if re.search(r"(?:password|secret|token|api[_-]?key|private[_-]?key|authorization)", key_text, re.I):
                        if nested not in (None, "", False):
                            findings.append(self._finding(SecretKind.API_KEY, nested_location, str(nested)))
                    walk(nested, nested_location, depth + 1)
                return
            if isinstance(item, (list, tuple)):
                for index, nested in enumerate(item):
                    walk(nested, f"{location}[{index}]", depth + 1)
                return
            if not isinstance(item, str):
                return
            for kind, pattern in self._PATTERNS:
                for match in pattern.finditer(item):
                    findings.append(self._finding(kind, location, match.group(0)))
            for token in re.findall(r"\b[A-Za-z0-9_-]{32,}\b", item):
                if self._looks_high_entropy(token):
                    findings.append(self._finding(SecretKind.HIGH_ENTROPY_TOKEN, location, token))

        walk(value, path, 0)
        unique: dict[tuple[SecretKind, str, str], SecretFinding] = {}
        for finding in findings:
            unique[(finding.kind, finding.location, finding.fingerprint)] = finding
        return list(unique.values())

    @staticmethod
    def _finding(kind: SecretKind, location: str, raw: str) -> SecretFinding:
        fingerprint = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
        return SecretFinding(kind, location, fingerprint)

    @staticmethod
    def _looks_high_entropy(token: str) -> bool:
        classes = sum(
            bool(pattern.search(token))
            for pattern in (re.compile(r"[a-z]"), re.compile(r"[A-Z]"), re.compile(r"\d"), re.compile(r"[_-]"))
        )
        return classes >= 3 and len(set(token)) >= 12


@dataclass(frozen=True)
class EgressPolicy:
    allow_sensitive: bool = False
    allow_secrets: bool = False
    allowed_fields: tuple[str, ...] = ()
    denied_fields: tuple[str, ...] = ()
    max_payload_bytes: int = 1_000_000


class ToolEgressGuard:
    """Fail-closed pre-call guard for accidental secret/data exfiltration."""

    def __init__(self, scanner: SecretScanner | None = None) -> None:
        self.scanner = scanner or SecretScanner()

    def check(self, arguments: Mapping[str, Any], policy: EgressPolicy) -> dict[str, Any]:
        serialized = json.dumps(arguments, ensure_ascii=False, default=str).encode("utf-8")
        if len(serialized) > policy.max_payload_bytes:
            return {"allowed": False, "reason": "payload_too_large", "size_bytes": len(serialized)}
        keys = {str(key) for key in arguments}
        denied = sorted(keys & set(policy.denied_fields))
        if denied:
            return {"allowed": False, "reason": "denied_fields", "fields": denied}
        if policy.allowed_fields:
            unknown = sorted(keys - set(policy.allowed_fields))
            if unknown:
                return {"allowed": False, "reason": "fields_not_allowlisted", "fields": unknown}
        findings = self.scanner.scan(arguments)
        if findings and not policy.allow_secrets:
            return {
                "allowed": False,
                "reason": "secret_detected",
                "findings": [asdict(finding) | {"kind": finding.kind.value} for finding in findings],
            }
        return {"allowed": True, "size_bytes": len(serialized), "secret_findings": len(findings)}


def normalize_tool_result(
    tool_id: str,
    raw: Any,
    *,
    source: str = "tool",
    version: str = "",
    query: str = "",
    retrieval_mode: str = "",
) -> ToolResultEnvelope:
    """Normalize common tool payload conventions without claiming completeness."""
    warnings: list[str] = []
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    resources: list[ResourceIdentity] = []
    pagination = PaginationState()
    data = raw

    if isinstance(raw, Mapping):
        if raw.get("error"):
            errors.append(str(raw.get("error")))
        raw_warnings = raw.get("warnings")
        if isinstance(raw_warnings, Sequence) and not isinstance(raw_warnings, (str, bytes)):
            warnings.extend(str(item) for item in raw_warnings)
        elif raw_warnings:
            warnings.append(str(raw_warnings))
        next_cursor = raw.get("next_cursor") or raw.get("nextCursor")
        has_more = bool(raw.get("has_more") or raw.get("hasMore") or next_cursor)
        truncated = bool(raw.get("truncated") or raw.get("is_truncated"))
        pagination = PaginationState(
            next_cursor=None if next_cursor is None else str(next_cursor),
            has_more=has_more,
            page=int(raw["page"]) if isinstance(raw.get("page"), int) else None,
            total_known=int(raw["total"]) if isinstance(raw.get("total"), int) else None,
            complete=not has_more and not truncated,
        )
        resource_id = raw.get("resource_id") or raw.get("id")
        resource_uri = raw.get("resource_uri") or raw.get("uri") or raw.get("url")
        if resource_id or resource_uri:
            resources.append(
                ResourceIdentity(
                    resource_type=str(raw.get("resource_type") or "unknown"),
                    resource_id=str(resource_id or resource_uri),
                    version=str(raw.get("version") or ""),
                    uri=str(resource_uri or ""),
                    etag=str(raw.get("etag") or ""),
                )
            )
        metadata = {
            key: raw[key]
            for key in ("status", "count", "total", "page", "truncated")
            if key in raw
        }

    explicit_partial = isinstance(raw, Mapping) and str(raw.get("status", "")).casefold() in {
        "partial",
        "partial_success",
        "partially_completed",
    }
    if errors and data is not None and isinstance(raw, Mapping) and len(raw) > 1:
        status = ToolResultStatus.PARTIAL_SUCCESS
    elif errors:
        status = ToolResultStatus.FAILURE
    elif explicit_partial or not pagination.complete:
        status = ToolResultStatus.PARTIAL_SUCCESS
    else:
        status = ToolResultStatus.SUCCESS

    return ToolResultEnvelope(
        status=status,
        data=data,
        metadata=metadata,
        warnings=tuple(warnings),
        errors=tuple(errors),
        provenance=ToolProvenance(
            tool_id=tool_id,
            source=source,
            timestamp=time.time(),
            version=version,
            query=query,
            retrieval_mode=retrieval_mode,
        ),
        pagination=pagination,
        resources=tuple(resources),
    )
