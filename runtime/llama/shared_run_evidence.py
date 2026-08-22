#!/usr/bin/env python3
"""Build fail-closed evidence for one successful two-node llama.cpp M1 shared run."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from runtime.llama.rpc_spike import RpcEndpoint

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_BASELINE_TO_SHARED = timedelta(hours=1)
ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = {
    "bundle": ROOT / "services" / "scheduler" / "experiment_bundle.schema.json",
    "placement": ROOT / "services" / "scheduler" / "placement_decision.schema.json",
    "spike": Path(__file__).resolve().with_name("spike_result.schema.json"),
    "relay": ROOT / "runtime" / "network" / "relay_metrics.schema.json",
    "evidence": Path(__file__).resolve().with_name("shared_run_evidence.schema.json"),
}


class SharedRunEvidenceError(RuntimeError):
    """Raised when candidate shared-run evidence is incomplete or inconsistent."""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _read_document(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise SharedRunEvidenceError(f"{label} must not be a symlink")
    if not path.is_file():
        raise SharedRunEvidenceError(f"{label} must be an existing file")
    size = path.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise SharedRunEvidenceError(f"{label} must be 1..{MAX_JSON_BYTES} bytes")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SharedRunEvidenceError(f"{label} must contain strict finite UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SharedRunEvidenceError(f"{label} must contain a JSON object")
    return value, raw


def _load_schema(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SharedRunEvidenceError(f"schema is not an object: {path.name}")
    return value


def _validate(value: dict[str, Any], schema_path: Path, label: str) -> None:
    validator = Draft202012Validator(_load_schema(schema_path), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise SharedRunEvidenceError(f"{label} failed schema validation at {where}: {first.message}")


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SharedRunEvidenceError(f"{label} has invalid date-time") from exc
    if parsed.tzinfo is None:
        raise SharedRunEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _same_numbers(actual: list[Any], expected: list[Any]) -> bool:
    if len(actual) != len(expected):
        return False
    return all(
        isinstance(a, (int, float))
        and not isinstance(a, bool)
        and isinstance(b, (int, float))
        and not isinstance(b, bool)
        and math.isfinite(float(a))
        and math.isfinite(float(b))
        and math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
        for a, b in zip(actual, expected)
    )


def _shared_candidate(bundle: dict[str, Any]) -> dict[str, Any]:
    placement = bundle["placement_decision"]
    if placement["recommendation"]["mode"] != "shared_experiment":
        raise SharedRunEvidenceError("experiment bundle does not recommend shared_experiment")
    candidates = [
        candidate for candidate in placement["candidates"]
        if candidate.get("mode") == "shared_contiguous_layers"
    ]
    if len(candidates) != 1 or not candidates[0].get("feasible"):
        raise SharedRunEvidenceError("experiment bundle lacks one feasible shared_contiguous_layers candidate")
    if len(candidates[0].get("tensor_split", [])) != 2:
        raise SharedRunEvidenceError("shared candidate must contain exactly two tensor_split entries")
    return candidates[0]


def compare_results_dicts(baseline: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    """Compare already validated spike results without persisting temporary files."""
    if baseline["placement"]["mode"] != "local_baseline" or shared["placement"]["mode"] != "shared_rpc":
        raise SharedRunEvidenceError("comparison requires local_baseline and shared_rpc results")
    if baseline["model"]["sha256"] != shared["model"]["sha256"]:
        raise SharedRunEvidenceError("cannot compare different model digests")
    if baseline["correctness"]["prompt_sha256"] != shared["correctness"]["prompt_sha256"]:
        raise SharedRunEvidenceError("cannot compare different prompt digests")
    btoken = baseline["correctness"].get("token_ids_sha256")
    stoken = shared["correctness"].get("token_ids_sha256")
    basis = "token_ids_sha256" if btoken is not None and stoken is not None else "output_sha256"
    exact = baseline["correctness"].get(basis) == shared["correctness"].get(basis)

    def ratio(key: str) -> float | None:
        b = baseline["timings"].get(key)
        s = shared["timings"].get(key)
        if (
            isinstance(b, (int, float)) and not isinstance(b, bool)
            and isinstance(s, (int, float)) and not isinstance(s, bool)
            and math.isfinite(float(b)) and math.isfinite(float(s))
            and b > 0
        ):
            return float(s) / float(b)
        return None

    return {
        "model_sha256": baseline["model"]["sha256"],
        "prompt_sha256": baseline["correctness"]["prompt_sha256"],
        "exact_output_match": exact,
        "match_basis": basis,
        "shared_over_baseline": {
            "prompt_tokens_per_second": ratio("prompt_per_second"),
            "predicted_tokens_per_second": ratio("predicted_per_second"),
            "request_ms": ratio("request_ms"),
        },
    }


def _require_device_order(baseline: dict[str, Any], shared: dict[str, Any]) -> None:
    bplace, splace = baseline["placement"], shared["placement"]
    if len(bplace["devices"]) != 1 or not _same_numbers(bplace["tensor_split"], [1.0]):
        raise SharedRunEvidenceError("baseline must use exactly one local device with tensor_split [1.0]")
    if len(splace["devices"]) != 2:
        raise SharedRunEvidenceError("shared run must use exactly two devices")
    local_device = bplace["devices"][0]
    shared_local, shared_rpc = splace["devices"]
    if "RPC" in local_device.upper():
        raise SharedRunEvidenceError("baseline device must be local, not RPC")
    if shared_local != local_device or "RPC" in shared_local.upper():
        raise SharedRunEvidenceError("first shared device must equal the coordinator baseline device")
    if "RPC" not in shared_rpc.upper():
        raise SharedRunEvidenceError("second shared device must be the RPC worker device")


def _require_runtime_binding(
    bundle: dict[str, Any],
    baseline: dict[str, Any],
    shared: dict[str, Any],
    relay: dict[str, Any],
) -> dict[str, Any]:
    candidate = _shared_candidate(bundle)
    model = bundle["placement_decision"]["model"]
    digest = model["artifact_digest"].removeprefix("sha256:")
    basename = bundle["benchmark_model_name"]

    for value, label in ((baseline, "baseline"), (shared, "shared")):
        if value["model"]["sha256"] != digest:
            raise SharedRunEvidenceError(f"{label} model digest does not match experiment bundle")
        if value["model"]["size_bytes"] != model["artifact_size_bytes"]:
            raise SharedRunEvidenceError(f"{label} model size does not match experiment bundle")
        if value["model"]["basename"] != basename:
            raise SharedRunEvidenceError(f"{label} model basename does not match experiment bundle")

    if baseline["runtime"] != shared["runtime"]:
        raise SharedRunEvidenceError("baseline and shared run must use the same llama.cpp runtime version")
    if baseline["correctness"]["prompt_sha256"] != shared["correctness"]["prompt_sha256"]:
        raise SharedRunEvidenceError("baseline and shared run prompt digests differ")

    bplace, splace = baseline["placement"], shared["placement"]
    if bplace["mode"] != "local_baseline" or bplace["split_mode"] != "none":
        raise SharedRunEvidenceError("baseline placement must be local_baseline with split_mode none")
    if splace["mode"] != "shared_rpc" or splace["split_mode"] != "layer":
        raise SharedRunEvidenceError("shared placement must be shared_rpc with split_mode layer")
    _require_device_order(baseline, shared)
    if not _same_numbers(splace["tensor_split"], candidate["tensor_split"]):
        raise SharedRunEvidenceError("shared run tensor_split does not match planner-selected split")
    if baseline["topology"]["rpc_endpoints"]:
        raise SharedRunEvidenceError("baseline must not contain RPC endpoints")
    if shared["topology"]["rpc_endpoints"] != [relay["listen"]]:
        raise SharedRunEvidenceError("shared run must use exactly the measurement relay listen endpoint")
    try:
        RpcEndpoint.parse(relay["target"])
    except ValueError as exc:
        raise SharedRunEvidenceError("relay target must be a literal loopback/RFC1918 RPC endpoint") from exc

    configured = relay["configured"]
    if configured["one_way_delay_ms"] != 0 or configured["jitter_ms"] != 0:
        raise SharedRunEvidenceError("first shared proof requires zero configured relay delay/jitter")
    if configured["disconnect_after_bytes"] is not None or configured["disconnect_after_seconds"] is not None:
        raise SharedRunEvidenceError("first shared proof must not configure relay disconnect injection")
    if relay["connected_at"] is None or relay["termination"]["reason"] != "eof":
        raise SharedRunEvidenceError("relay must record a connected run ending by eof")
    traffic = relay["traffic"]
    if traffic["coordinator_to_worker_bytes"] <= 0 or traffic["worker_to_coordinator_bytes"] <= 0:
        raise SharedRunEvidenceError("relay must record positive traffic in both directions")
    if traffic["total_forwarded_bytes"] != (
        traffic["coordinator_to_worker_bytes"] + traffic["worker_to_coordinator_bytes"]
    ):
        raise SharedRunEvidenceError("relay total_forwarded_bytes does not equal directional byte sum")

    bundle_captured = _parse_time(bundle["captured_at"], "bundle.captured_at")
    baseline_captured = _parse_time(baseline["captured_at"], "baseline.captured_at")
    started = _parse_time(relay["started_at"], "relay.started_at")
    connected = _parse_time(relay["connected_at"], "relay.connected_at")
    ended = _parse_time(relay["ended_at"], "relay.ended_at")
    shared_captured = _parse_time(shared["captured_at"], "shared.captured_at")
    if not bundle_captured <= baseline_captured <= started <= connected <= ended:
        raise SharedRunEvidenceError("proof timestamps must follow bundle -> baseline -> relay start/connect/end")
    if shared_captured < connected or shared_captured > ended + timedelta(minutes=5):
        raise SharedRunEvidenceError("shared result timestamp is not plausibly associated with the relay run")
    if shared_captured < baseline_captured or shared_captured - baseline_captured > MAX_BASELINE_TO_SHARED:
        raise SharedRunEvidenceError("baseline and shared result must be ordered and captured within one hour")

    comparison = compare_results_dicts(baseline, shared)
    if not comparison["exact_output_match"]:
        raise SharedRunEvidenceError("shared run does not exactly match the local baseline")
    return comparison


def build_shared_run_evidence(
    *,
    bundle_path: Path,
    baseline_path: Path,
    shared_path: Path,
    relay_path: Path,
) -> dict[str, Any]:
    bundle, bundle_raw = _read_document(bundle_path, "experiment bundle")
    baseline, baseline_raw = _read_document(baseline_path, "baseline result")
    shared, shared_raw = _read_document(shared_path, "shared result")
    relay, relay_raw = _read_document(relay_path, "relay metrics")

    _validate(bundle, SCHEMAS["bundle"], "experiment bundle")
    _validate(bundle["placement_decision"], SCHEMAS["placement"], "placement decision")
    _validate(baseline, SCHEMAS["spike"], "baseline result")
    _validate(shared, SCHEMAS["spike"], "shared result")
    _validate(relay, SCHEMAS["relay"], "relay metrics")
    comparison = _require_runtime_binding(bundle, baseline, shared, relay)
    candidate = _shared_candidate(bundle)

    source_digests = {
        "experiment_bundle": _digest(bundle_raw),
        "baseline": _digest(baseline_raw),
        "shared": _digest(shared_raw),
        "relay": _digest(relay_raw),
    }
    evidence_id = "shared-run-evidence-" + _canonical_digest({
        "bundle_id": bundle["bundle_id"],
        "sources": source_digests,
        "comparison": comparison,
    })[:16]
    evidence = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": "m1_two_node_shared_runtime_proof",
        "experiment_bundle_id": bundle["bundle_id"],
        "placement_decision_id": bundle["placement_decision"]["decision_id"],
        "model": {
            "basename": shared["model"]["basename"],
            "size_bytes": shared["model"]["size_bytes"],
            "sha256": shared["model"]["sha256"],
        },
        "runtime": baseline["runtime"],
        "planner_split": {
            "tensor_split": list(candidate["tensor_split"]),
            "layer_ranges": list(candidate["layer_ranges"]),
        },
        "sources": {
            "experiment_bundle": {
                "file_name": bundle_path.name,
                "document_sha256": source_digests["experiment_bundle"],
                "bundle_id": bundle["bundle_id"],
            },
            "baseline": {
                "file_name": baseline_path.name,
                "document_sha256": source_digests["baseline"],
                "run_id": baseline["run_id"],
            },
            "shared": {
                "file_name": shared_path.name,
                "document_sha256": source_digests["shared"],
                "run_id": shared["run_id"],
            },
            "relay": {
                "file_name": relay_path.name,
                "document_sha256": source_digests["relay"],
                "listen": relay["listen"],
                "target": relay["target"],
            },
        },
        "correctness": {
            "prompt_sha256": comparison["prompt_sha256"],
            "exact_output_match": True,
            "match_basis": comparison["match_basis"],
            "baseline_output_sha256": baseline["correctness"]["output_sha256"],
            "shared_output_sha256": shared["correctness"]["output_sha256"],
            "baseline_token_ids_sha256": baseline["correctness"]["token_ids_sha256"],
            "shared_token_ids_sha256": shared["correctness"]["token_ids_sha256"],
        },
        "performance": {
            "baseline_request_ms": baseline["timings"]["request_ms"],
            "shared_request_ms": shared["timings"]["request_ms"],
            "baseline_prompt_tokens_per_second": baseline["timings"]["prompt_per_second"],
            "shared_prompt_tokens_per_second": shared["timings"]["prompt_per_second"],
            "baseline_predicted_tokens_per_second": baseline["timings"]["predicted_per_second"],
            "shared_predicted_tokens_per_second": shared["timings"]["predicted_per_second"],
            "shared_over_baseline": comparison["shared_over_baseline"],
            "relay_setup_elapsed_ms": relay["setup_elapsed_ms"],
            "relay_active_elapsed_ms": relay["active_elapsed_ms"],
            "relay_total_elapsed_ms": relay["total_elapsed_ms"],
            "coordinator_to_worker_bytes": relay["traffic"]["coordinator_to_worker_bytes"],
            "worker_to_coordinator_bytes": relay["traffic"]["worker_to_coordinator_bytes"],
            "total_forwarded_bytes": relay["traffic"]["total_forwarded_bytes"],
        },
        "production_scheduling": False,
    }
    _validate(evidence, SCHEMAS["evidence"], "shared run evidence")
    return evidence


def write_shared_run_evidence(
    *,
    bundle_path: Path,
    baseline_path: Path,
    shared_path: Path,
    relay_path: Path,
    output_path: Path,
) -> Path:
    evidence = build_shared_run_evidence(
        bundle_path=bundle_path,
        baseline_path=baseline_path,
        shared_path=shared_path,
        relay_path=relay_path,
    )
    if output_path.exists():
        raise SharedRunEvidenceError("output path already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build fail-closed ComputeMesh M1 shared-runtime evidence"
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--shared", type=Path, required=True)
    parser.add_argument("--relay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(write_shared_run_evidence(
        bundle_path=args.bundle,
        baseline_path=args.baseline,
        shared_path=args.shared,
        relay_path=args.relay,
        output_path=args.output,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
