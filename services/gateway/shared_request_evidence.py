"""Verify single-pass shared-request evidence before provider settlement."""
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


class SharedRequestEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedSharedRequestEvidence:
    evidence_id: str
    document_sha256: str
    placement_decision_id: str
    model_sha256: str
    runtime_sha256: str
    output_sha256: str
    provider_shares: tuple[tuple[str, float], ...]
    captured_at: datetime


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file() or not (0 < path.stat().st_size <= MAX_EVIDENCE_BYTES):
        raise SharedRequestEvidenceError("shared-request evidence must be a bounded regular file")
    raw = path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SharedRequestEvidenceError("shared-request evidence must contain strict UTF-8 JSON") from exc
    if not isinstance(doc, dict):
        raise SharedRequestEvidenceError("shared-request evidence root must be an object")
    schema_path = Path(__file__).resolve().parents[2] / "runtime" / "llama" / "shared_request_evidence.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "$"
        raise SharedRequestEvidenceError(f"shared-request evidence invalid at {where}: {first.message}")
    return doc, raw


def _ranges(items: Any) -> tuple[tuple[str, int, int], ...]:
    try:
        values = tuple((str(x["node_id"]), int(x["start_layer"]), int(x["end_layer_exclusive"])) for x in items)
    except (KeyError, TypeError, ValueError) as exc:
        raise SharedRequestEvidenceError("invalid planner layer ranges") from exc
    return tuple(sorted(values, key=lambda x: x[1]))


def _shares(ranges: tuple[tuple[str, int, int], ...]) -> tuple[tuple[str, float], ...]:
    lengths = [(node, end - start) for node, start, end in ranges]
    if any(length <= 0 for _, length in lengths):
        raise SharedRequestEvidenceError("invalid layer allocation")
    total = sum(length for _, length in lengths)
    result = tuple((node, length / total) for node, length in lengths)
    if not math.isclose(sum(v for _, v in result), 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise SharedRequestEvidenceError("provider shares do not normalize")
    return result


def verify_shared_request_evidence(
    evidence_path: str | Path,
    *,
    placement: PlacementSelection,
    job_id: str,
    output_text: str,
    prompt_tokens: int,
    completion_tokens: int,
    not_before: datetime,
    now: datetime | None = None,
) -> VerifiedSharedRequestEvidence:
    if not_before.tzinfo is None:
        raise ValueError("not_before must be timezone-aware")
    doc, raw = _load(Path(evidence_path))
    if doc["job_id"] != job_id:
        raise SharedRequestEvidenceError("evidence job_id does not match orchestrator job")
    if doc["placement_decision_id"] != placement.decision_id:
        raise SharedRequestEvidenceError("evidence placement does not match scheduler dispatch")
    if doc["model"]["sha256"] != placement.artifact_digest.removeprefix("sha256:"):
        raise SharedRequestEvidenceError("evidence model digest does not match scheduler artifact")
    actual_ranges = _ranges(doc["planner_split"]["layer_ranges"])
    expected_ranges = tuple(sorted(placement.layer_ranges, key=lambda x: x[1]))
    if actual_ranges != expected_ranges:
        raise SharedRequestEvidenceError("evidence layer ranges do not match scheduler placement")
    if tuple(doc["participants"]) != placement.provider_node_ids:
        raise SharedRequestEvidenceError("evidence participants do not match reserved providers")
    output_sha = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
    if doc["request"]["output_sha256"] != output_sha:
        raise SharedRequestEvidenceError("evidence output digest does not match returned text")
    if int(doc["request"]["prompt_tokens"]) != prompt_tokens or int(doc["request"]["completion_tokens"]) != completion_tokens:
        raise SharedRequestEvidenceError("evidence usage does not match runtime result")
    base = {k: v for k, v in doc.items() if k != "evidence_id"}
    expected_id = "shared-request-evidence-" + _digest(base)[:16]
    if doc["evidence_id"] != expected_id:
        raise SharedRequestEvidenceError("evidence id does not match document claims")
    try:
        captured = datetime.fromisoformat(doc["captured_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError) as exc:
        raise SharedRequestEvidenceError("invalid evidence timestamp") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if captured < not_before.astimezone(timezone.utc) - timedelta(seconds=5):
        raise SharedRequestEvidenceError("evidence predates current execution")
    if captured > current + timedelta(minutes=5):
        raise SharedRequestEvidenceError("evidence timestamp is implausibly in the future")
    return VerifiedSharedRequestEvidence(
        evidence_id=doc["evidence_id"],
        document_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
        placement_decision_id=placement.decision_id,
        model_sha256=doc["model"]["sha256"],
        runtime_sha256=_digest(doc["runtime"]),
        output_sha256=output_sha,
        provider_shares=_shares(actual_ranges),
        captured_at=captured,
    )
