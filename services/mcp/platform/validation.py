"""Validation, evidence/provenance and structured error recovery contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid


class ErrorCode(str, Enum):
    NO_SKILL_MATCH = "NO_SKILL_MATCH"
    AMBIGUOUS_ROUTE = "AMBIGUOUS_ROUTE"
    SKILL_PARSE_ERROR = "SKILL_PARSE_ERROR"
    SKILL_VERSION_ERROR = "SKILL_VERSION_ERROR"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    DEPENDENCY_CYCLE = "DEPENDENCY_CYCLE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"
    TOOL_SCHEMA_ERROR = "TOOL_SCHEMA_ERROR"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_RATE_LIMIT = "TOOL_RATE_LIMIT"
    DATA_MISSING = "DATA_MISSING"
    DATA_CONFLICT = "DATA_CONFLICT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONTEXT_LIMIT = "CONTEXT_LIMIT"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    USER_CONFIRMATION_REQUIRED = "USER_CONFIRMATION_REQUIRED"
    OUTPUT_CONTRACT_FAILED = "OUTPUT_CONTRACT_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class RecoveryAction(str, Enum):
    NONE = "NONE"
    RETRY = "RETRY"
    FALLBACK_TOOL = "FALLBACK_TOOL"
    FALLBACK_SKILL = "FALLBACK_SKILL"
    REROUTE = "REROUTE"
    REQUEST_INPUT = "REQUEST_INPUT"
    ABORT = "ABORT"


@dataclass(frozen=True)
class PlatformError:
    code: ErrorCode
    message: str
    retryable: bool = False
    recovery: RecoveryAction = RecoveryAction.NONE
    source: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["code"] = self.code.value
        value["recovery"] = self.recovery.value
        return value


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    claim: str
    value: Any
    source_type: str
    source_ref: str
    retrieved_at: float
    valid_as_of: str
    confidence: float
    used_by_tasks: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        payload = json.dumps(
            {
                "claim": self.claim,
                "value": self.value,
                "source_type": self.source_type,
                "source_ref": self.source_ref,
                "valid_as_of": self.valid_as_of,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["digest"] = self.digest
        return value


class EvidenceLedger:
    """In-memory request-level evidence ledger with explicit provenance classes."""

    ALLOWED_SOURCE_TYPES = {
        "USER",
        "FILE",
        "WEB",
        "DATABASE",
        "TOOL",
        "CALCULATION",
        "ASSUMPTION",
        "SYSTEM",
    }

    def __init__(self) -> None:
        self._records: dict[str, EvidenceRecord] = {}

    def add(
        self,
        claim: str,
        value: Any,
        *,
        source_type: str,
        source_ref: str,
        valid_as_of: str = "",
        confidence: float = 1.0,
        used_by_tasks: Sequence[str] = (),
        contradictions: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        source = str(source_type).upper()
        if source not in self.ALLOWED_SOURCE_TYPES:
            raise ValueError(f"unsupported evidence source type: {source}")
        claim = str(claim or "").strip()
        if not claim:
            raise ValueError("evidence claim is required")
        if source != "ASSUMPTION" and not str(source_ref or "").strip():
            raise ValueError("source_ref is required for non-assumption evidence")
        confidence_value = float(confidence)
        if not 0.0 <= confidence_value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        record = EvidenceRecord(
            evidence_id=f"ev_{uuid.uuid4().hex}",
            claim=claim,
            value=value,
            source_type=source,
            source_ref=str(source_ref or ""),
            retrieved_at=time.time(),
            valid_as_of=str(valid_as_of or ""),
            confidence=confidence_value,
            used_by_tasks=tuple(str(x) for x in used_by_tasks),
            contradictions=tuple(str(x) for x in contradictions),
            metadata=dict(metadata or {}),
        )
        self._records[record.evidence_id] = record
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._records.get(evidence_id)

    def list(self) -> list[EvidenceRecord]:
        return list(self._records.values())

    def conflicts(self, claim: str) -> list[EvidenceRecord]:
        records = [record for record in self._records.values() if record.claim == claim]
        distinct = {json.dumps(record.value, sort_keys=True, default=str) for record in records}
        return records if len(distinct) > 1 else []


@dataclass(frozen=True)
class ValidationResult:
    validator: str
    passed: bool
    message: str = ""
    severity: str = "ERROR"
    evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    passed: bool
    results: tuple[ValidationResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "results": [asdict(result) for result in self.results]}


Validator = Callable[[Any, Mapping[str, Any]], ValidationResult | bool]


class ValidationEngine:
    """Named validator registry used for task and output completion gates."""

    def __init__(self) -> None:
        self._validators: dict[str, Validator] = {}
        self.register("not_none", self._not_none)
        self.register("non_empty", self._non_empty)
        self.register("no_error_field", self._no_error_field)

    def register(self, name: str, validator: Validator) -> None:
        name = str(name or "").strip()
        if not name:
            raise ValueError("validator name is required")
        self._validators[name] = validator

    def run(
        self,
        value: Any,
        validators: Iterable[str],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> ValidationReport:
        ctx = dict(context or {})
        results: list[ValidationResult] = []
        for name in validators:
            validator = self._validators.get(str(name))
            if validator is None:
                results.append(ValidationResult(str(name), False, "validator not registered", "ERROR"))
                continue
            try:
                result = validator(value, ctx)
                if isinstance(result, ValidationResult):
                    results.append(result)
                else:
                    results.append(ValidationResult(str(name), bool(result), "" if result else "validation failed"))
            except Exception as exc:
                results.append(ValidationResult(str(name), False, f"validator raised: {exc}"))
        return ValidationReport(all(result.passed for result in results), tuple(results))

    @staticmethod
    def _not_none(value: Any, _: Mapping[str, Any]) -> ValidationResult:
        return ValidationResult("not_none", value is not None, "" if value is not None else "value is None")

    @staticmethod
    def _non_empty(value: Any, _: Mapping[str, Any]) -> ValidationResult:
        try:
            passed = len(value) > 0  # type: ignore[arg-type]
        except Exception:
            passed = bool(value)
        return ValidationResult("non_empty", passed, "" if passed else "value is empty")

    @staticmethod
    def _no_error_field(value: Any, _: Mapping[str, Any]) -> ValidationResult:
        passed = not (isinstance(value, Mapping) and value.get("error"))
        return ValidationResult("no_error_field", passed, "" if passed else "result contains error")


def classify_exception(exc: Exception, *, source: str = "") -> PlatformError:
    """Map common runtime errors into stable error/recovery contracts."""
    text = str(exc)
    lower = text.casefold()
    if isinstance(exc, TimeoutError) or "timeout" in lower:
        return PlatformError(ErrorCode.TOOL_TIMEOUT, text, True, RecoveryAction.RETRY, source)
    if "rate limit" in lower or "429" in lower:
        return PlatformError(ErrorCode.TOOL_RATE_LIMIT, text, True, RecoveryAction.RETRY, source)
    if "permission" in lower or "unauthor" in lower or "forbidden" in lower:
        return PlatformError(ErrorCode.TOOL_PERMISSION_DENIED, text, False, RecoveryAction.ABORT, source)
    if "schema" in lower or "argument" in lower or "parameter" in lower:
        return PlatformError(ErrorCode.TOOL_SCHEMA_ERROR, text, False, RecoveryAction.REROUTE, source)
    if "dependency" in lower and "cycle" in lower:
        return PlatformError(ErrorCode.DEPENDENCY_CYCLE, text, False, RecoveryAction.ABORT, source)
    if "dependency" in lower or "missing" in lower:
        return PlatformError(ErrorCode.DEPENDENCY_MISSING, text, False, RecoveryAction.FALLBACK_SKILL, source)
    return PlatformError(ErrorCode.UNKNOWN_ERROR, text, False, RecoveryAction.REROUTE, source)
