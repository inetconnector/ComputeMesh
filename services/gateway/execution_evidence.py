"""Verify M1 shared-run evidence before it can drive provider settlement."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from services.gateway.placement_selection import PlacementSelection

MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
DEFAULT_FUTURE_SKEW = timedelta(minutes=5)


class ExecutionEvidenceError(ValueError):
    """Raised when runtime evidence is unsafe to use for provider settlement."""


@dataclass(frozen=True)
class VerifiedExecutionEvidence:
    evidence_id: str
    document_sha256: str
    placement_decision_id: str
    model_sha256: str
    runtime_sha256: str
    output_sha256: str
    provider_shares: tuple[tuple[str, float], ...]
    captured_at: datetime


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _load_document(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise ExecutionEvidenceError("shared-run evidence must not be a symlink")
    if not path.is_file():
        raise ExecutionEvidenceError("shared-run evidence must be an existing file")
    size = path.stat().st_size
    if size <= 0 or size > MAX_EVIDENCE_BYTES:
        raise ExecutionEvidenceError(
            f"shared-run evidence must be 1..{MAX_EVIDENCE_BYTES} bytes"
        )
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExecutionEvidenceError("shared-run evidence must be strict finite UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ExecutionEvidenceError("shared-run evidence root must be an object")
    return value, raw


def _load_schema() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "runtime" / "llama" / "shared_run_evidence.schema.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutionEvidenceError("shared-run evidence schema could not be loaded") from exc
    if not isinstance(value, dict):
        raise ExecutionEvidenceError("shared-run evidence schema is invalid")
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ExecutionEvidenceError("evidence captured_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ExecutionEvidenceError("evidence captured_at must include timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _verify_evidence_id(evidence: dict[str, Any]) -> None:
    source_digests = {
        name: evidence["sources"][name]["document_sha256"]
        for name in ("experiment_bundle", "baseline", "shared", "relay")
    }
    comparison = {
        "model_sha256": evidence["model"]["sha256"],
        "prompt_sha256": evidence["correctness"]["prompt_sha256"],
        "exact_output_match": evidence["correctness"]["exact_output_match"],
        "match_basis": evidence["correctness"]["match_basis"],
        "shared_over_baseline": evidence["performance"]["shared_over_baseline"],
    }
    expected = "shared-run-evidence-" + _canonical_digest(
        {
            "bundle_id": evidence["experiment_bundle_id"],
            "sources": source_digests,
            "comparison": comparison,
        }
    )[:16]
    if evidence["evidence_id"] != expected:
        raise ExecutionEvidenceError("shared-run evidence id does not match its bound sources")


def _normalized_ranges(items: Any) -> tuple[tuple[str, int, int], ...]:
    try:
        ranges = tuple(
            (
                str(item["node_id"]),
                int(item["start_layer"]),
                int(item["end_layer_exclusive"]),
            )
            for item in items
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionEvidenceError("evidence planner layer ranges are invalid") from exc
    return tuple(sorted(ranges, key=lambda item: item[1]))


def _provider_shares(
    ranges: tuple[tuple[str, int, int], ...]
) -> tuple[tuple[str, float], ...]:
    lengths: list[tuple[str, int]] = []
    for node_id, start, end in ranges:
        length = end - start
        if length <= 0:
            raise ExecutionEvidenceError("evidence contains an empty or reversed layer range")
        lengths.append((node_id, length))
    total = sum(length for _, length in lengths)
    if total <= 0:
        raise ExecutionEvidenceError("evidence has no billable layer allocation")
    shares = tuple((node_id, length / total) for node_id, length in lengths)
    if not math.isclose(sum(value for _, value in shares), 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise ExecutionEvidenceError("provider shares do not normalize to one")
    return shares


def verify_shared_execution_evidence(
    evidence_path: str | Path,
    *,
    placement: PlacementSelection,
    output_text: str,
    not_before: datetime,
    now: datetime | None = None,
) -> VerifiedExecutionEvidence:
    """Validate and bind one shared-run proof to the just-finished runtime output."""
    if not_before.tzinfo is None:
        raise ValueError("not_before must be timezone-aware")
    evidence, raw = _load_document(Path(evidence_path))
    validator = Draft202012Validator(_load_schema(), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(evidence), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "$"
        raise ExecutionEvidenceError(f"shared-run evidence invalid at {where}: {first.message}")

    _verify_evidence_id(evidence)
    if evidence["placement_decision_id"] != placement.decision_id:
        raise ExecutionEvidenceError("evidence placement decision does not match dispatch placement")
    expected_model_digest = placement.artifact_digest.removeprefix("sha256:")
    if evidence["model"]["sha256"] != expected_model_digest:
        raise ExecutionEvidenceError("evidence model digest does not match dispatch artifact")

    actual_ranges = _normalized_ranges(evidence["planner_split"]["layer_ranges"])
    expected_ranges = tuple(sorted(placement.layer_ranges, key=lambda item: item[1]))
    if actual_ranges != expected_ranges:
        raise ExecutionEvidenceError("evidence layer ranges do not match scheduler placement")
    if tuple(node_id for node_id, _, _ in actual_ranges) != tuple(
        node_id for node_id, _, _ in expected_ranges
    ):
        raise ExecutionEvidenceError("evidence provider order does not match scheduler placement")

    output_sha256 = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
    if evidence["correctness"]["shared_output_sha256"] != output_sha256:
        raise ExecutionEvidenceError("evidence output digest does not match current runtime output")

    captured_at = _parse_time(evidence["captured_at"])
    lower_bound = not_before.astimezone(timezone.utc) - timedelta(seconds=5)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if captured_at < lower_bound:
        raise ExecutionEvidenceError("shared-run evidence predates the current execution")
    if captured_at > current + DEFAULT_FUTURE_SKEW:
        raise ExecutionEvidenceError("shared-run evidence timestamp is implausibly in the future")

    provider_shares = _provider_shares(actual_ranges)
    if {provider for provider, _ in provider_shares} != set(placement.provider_node_ids):
        raise ExecutionEvidenceError("evidence participants do not match reserved provider nodes")

    return VerifiedExecutionEvidence(
        evidence_id=str(evidence["evidence_id"]),
        document_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        placement_decision_id=placement.decision_id,
        model_sha256=evidence["model"]["sha256"],
        runtime_sha256=_canonical_digest(evidence["runtime"]),
        output_sha256=output_sha256,
        provider_shares=provider_shares,
        captured_at=captured_at,
    )
