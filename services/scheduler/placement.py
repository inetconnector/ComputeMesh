#!/usr/bin/env python3
"""Deterministic two-node feasibility planner for the narrow M1 llama.cpp experiment.

This module deliberately separates *feasibility* from performance claims. It
uses measured node profiles/llama-bench/network records plus an explicit model
manifest and layer count. Until a correct shared runtime result exists, it does
not predict or claim a shared speedup.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "protocol" / "schemas"
DECISION_SCHEMA = Path(__file__).with_name("placement_decision.schema.json")


class PlacementInputError(ValueError):
    pass


@dataclass(frozen=True)
class PlannerPolicy:
    max_profile_age_hours: float = 24.0
    planner_memory_fraction: float = 0.90
    fixed_model_overhead_fraction: float = 0.10

    def __post_init__(self) -> None:
        if not 0 < self.max_profile_age_hours <= 24 * 30:
            raise ValueError("max_profile_age_hours must be >0 and <=720")
        if not 0 < self.planner_memory_fraction <= 1:
            raise ValueError("planner_memory_fraction must be >0 and <=1")
        if not 0 <= self.fixed_model_overhead_fraction < 0.5:
            raise ValueError("fixed_model_overhead_fraction must be >=0 and <0.5")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlacementInputError(f"{path}: JSON root must be an object")
    return payload


def _load_schema(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid schema: {path}")
    return payload


def _validate(payload: dict[str, Any], schema_path: Path, label: str) -> None:
    validator = Draft202012Validator(_load_schema(schema_path), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise PlacementInputError(f"{label} invalid at {location}: {first.message}")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlacementInputError("invalid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise PlacementInputError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _age_hours(value: str, now: datetime) -> float:
    captured = _parse_time(value)
    return max(0.0, (now - captured).total_seconds() / 3600.0)


def _metric(result: dict[str, Any], name: str) -> float:
    value = result.get("metrics", {}).get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise PlacementInputError(f"benchmark metric {name!r} must be positive")
    return float(value)


def _select_memory_device(profile: dict[str, Any]) -> dict[str, Any]:
    devices = [
        device
        for device in profile["devices"]
        if device["kind"] in {"gpu", "accelerator"} and int(device["memory_total_bytes"]) > 0
    ]
    if devices:
        device = sorted(devices, key=lambda item: (-int(item["memory_total_bytes"]), item["device_id"]))[0]
        return {
            "device_id": device["device_id"],
            "kind": device["kind"],
            "name": device["name"],
            "raw_memory_bytes": int(device["memory_total_bytes"]),
        }
    return {
        "device_id": "cpu:system-memory",
        "kind": "cpu",
        "name": profile["cpu"].get("model") or "CPU",
        "raw_memory_bytes": int(profile["memory"]["available_bytes"]),
    }


def _usable_memory(profile: dict[str, Any], policy: PlannerPolicy) -> dict[str, Any]:
    device = _select_memory_device(profile)
    provider_fraction = profile["provider_limits"].get("max_memory_fraction")
    if isinstance(provider_fraction, bool) or not isinstance(provider_fraction, (int, float)):
        provider_fraction = 1.0
    effective_fraction = min(float(provider_fraction), policy.planner_memory_fraction)
    return {
        **device,
        "provider_memory_fraction": float(provider_fraction),
        "planner_memory_fraction": policy.planner_memory_fraction,
        "effective_memory_fraction": effective_fraction,
        "usable_memory_bytes": math.floor(device["raw_memory_bytes"] * effective_fraction),
    }


def _require_benchmark(
    result: dict[str, Any],
    *,
    expected_name: str,
    profile: dict[str, Any],
    label: str,
) -> None:
    if result["benchmark_name"] != expected_name:
        raise PlacementInputError(f"{label} must be {expected_name}")
    if int(result["profile_revision"]) != int(profile["profile_revision"]):
        raise PlacementInputError(f"{label} profile revision does not match node profile")


def _artifact(manifest: dict[str, Any], digest: str | None) -> dict[str, Any]:
    artifacts = manifest["artifacts"]
    if digest is None:
        if len(artifacts) != 1:
            raise PlacementInputError("--artifact-digest is required when manifest has multiple artifacts")
        return artifacts[0]
    normalized = digest if digest.startswith("sha256:") else f"sha256:{digest}"
    for artifact in artifacts:
        if artifact["digest"] == normalized:
            return artifact
    raise PlacementInputError("selected artifact digest is not present in model manifest")


def _model_benchmark_consistency(
    artifact: dict[str, Any],
    results: list[tuple[str, dict[str, Any]]],
) -> tuple[str, int]:
    expected_size = int(artifact["size_bytes"])
    names: set[str] = set()
    for label, result in results:
        metrics = result["metrics"]
        size = metrics.get("model_size_bytes")
        name = metrics.get("model_name")
        if isinstance(size, bool) or not isinstance(size, (int, float)) or int(size) != expected_size:
            raise PlacementInputError(f"{label} model_size_bytes does not match selected manifest artifact")
        if not isinstance(name, str) or not name:
            raise PlacementInputError(f"{label} missing model_name")
        names.add(name)
    if len(names) != 1:
        raise PlacementInputError("llama benchmarks do not refer to the same model basename")
    return next(iter(names)), expected_size


def _constraint(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail[:512]}


def _candidate_local(
    coordinator: dict[str, Any],
    *,
    model_size: int,
    layer_count: int,
) -> dict[str, Any]:
    feasible = coordinator["usable_memory_bytes"] >= model_size
    return {
        "mode": "local_only",
        "feasible": feasible,
        "layer_ranges": [
            {"node_id": coordinator["node_id"], "start_layer": 0, "end_layer_exclusive": layer_count}
        ] if feasible else [],
        "tensor_split": [1.0] if feasible else [],
        "explanation": (
            "selected coordinator memory budget can hold the complete artifact"
            if feasible
            else "selected coordinator memory budget cannot hold the complete artifact"
        ),
    }


def _candidate_shared(
    coordinator: dict[str, Any],
    worker: dict[str, Any],
    *,
    model_size: int,
    layer_count: int,
    fixed_overhead_fraction: float,
) -> dict[str, Any]:
    fixed_bytes = math.ceil(model_size * fixed_overhead_fraction)
    layer_pool_bytes = max(1, model_size - fixed_bytes)
    bytes_per_layer = max(1, math.ceil(layer_pool_bytes / layer_count))
    coordinator_layer_budget = max(0, coordinator["usable_memory_bytes"] - fixed_bytes)
    coordinator_max_layers = min(layer_count, coordinator_layer_budget // bytes_per_layer)
    worker_max_layers = min(layer_count, worker["usable_memory_bytes"] // bytes_per_layer)
    feasible = coordinator_max_layers >= 1 and worker_max_layers >= 1 and coordinator_max_layers + worker_max_layers >= layer_count
    if not feasible:
        return {
            "mode": "shared_contiguous_layers",
            "feasible": False,
            "layer_ranges": [],
            "tensor_split": [],
            "memory_model": {
                "fixed_coordinator_bytes": fixed_bytes,
                "estimated_layer_bytes": bytes_per_layer,
                "coordinator_max_layers": int(coordinator_max_layers),
                "worker_max_layers": int(worker_max_layers),
            },
            "explanation": "combined conservative layer budgets cannot place at least one layer on each node",
        }

    total_capacity = coordinator_max_layers + worker_max_layers
    worker_layers = max(1, round(layer_count * worker_max_layers / total_capacity))
    worker_layers = min(worker_layers, worker_max_layers, layer_count - 1)
    coordinator_layers = layer_count - worker_layers
    if coordinator_layers > coordinator_max_layers:
        deficit = coordinator_layers - coordinator_max_layers
        worker_layers += deficit
        coordinator_layers -= deficit
    if worker_layers > worker_max_layers or coordinator_layers < 1:
        raise RuntimeError("internal shared placement calculation violated memory bounds")

    return {
        "mode": "shared_contiguous_layers",
        "feasible": True,
        "layer_ranges": [
            {
                "node_id": coordinator["node_id"],
                "start_layer": 0,
                "end_layer_exclusive": int(coordinator_layers),
            },
            {
                "node_id": worker["node_id"],
                "start_layer": int(coordinator_layers),
                "end_layer_exclusive": layer_count,
            },
        ],
        "tensor_split": [float(coordinator_layers), float(worker_layers)],
        "memory_model": {
            "fixed_coordinator_bytes": fixed_bytes,
            "estimated_layer_bytes": bytes_per_layer,
            "coordinator_max_layers": int(coordinator_max_layers),
            "worker_max_layers": int(worker_max_layers),
        },
        "explanation": "contiguous two-node layer candidate derived from conservative selected-device memory budgets only",
    }


def build_placement_decision(
    *,
    coordinator_profile: dict[str, Any],
    worker_profile: dict[str, Any],
    model_manifest: dict[str, Any],
    coordinator_prefill: dict[str, Any],
    coordinator_decode: dict[str, Any],
    worker_prefill: dict[str, Any],
    worker_decode: dict[str, Any],
    network_result: dict[str, Any],
    network_peer_node_id: str,
    layer_count: int,
    artifact_digest: str | None = None,
    policy: PlannerPolicy = PlannerPolicy(),
    now: datetime | None = None,
) -> dict[str, Any]:
    if isinstance(layer_count, bool) or not isinstance(layer_count, int) or not 2 <= layer_count <= 100_000:
        raise PlacementInputError("layer_count must be an integer between 2 and 100000")
    if not isinstance(network_peer_node_id, str) or not network_peer_node_id:
        raise PlacementInputError("network_peer_node_id is required")

    for payload, schema, label in (
        (coordinator_profile, SCHEMA_ROOT / "node_profile.schema.json", "coordinator profile"),
        (worker_profile, SCHEMA_ROOT / "node_profile.schema.json", "worker profile"),
        (model_manifest, SCHEMA_ROOT / "model_manifest.schema.json", "model manifest"),
        (coordinator_prefill, SCHEMA_ROOT / "benchmark_result.schema.json", "coordinator prefill"),
        (coordinator_decode, SCHEMA_ROOT / "benchmark_result.schema.json", "coordinator decode"),
        (worker_prefill, SCHEMA_ROOT / "benchmark_result.schema.json", "worker prefill"),
        (worker_decode, SCHEMA_ROOT / "benchmark_result.schema.json", "worker decode"),
        (network_result, SCHEMA_ROOT / "benchmark_result.schema.json", "network result"),
    ):
        _validate(payload, schema, label)

    if coordinator_profile["node_id"] == worker_profile["node_id"]:
        raise PlacementInputError("coordinator and worker must have different node_id values")
    if network_peer_node_id != worker_profile["node_id"]:
        raise PlacementInputError("caller-asserted network peer node_id does not match worker profile")

    _require_benchmark(coordinator_prefill, expected_name="llama_cpp_prefill", profile=coordinator_profile, label="coordinator prefill")
    _require_benchmark(coordinator_decode, expected_name="llama_cpp_decode", profile=coordinator_profile, label="coordinator decode")
    _require_benchmark(worker_prefill, expected_name="llama_cpp_prefill", profile=worker_profile, label="worker prefill")
    _require_benchmark(worker_decode, expected_name="llama_cpp_decode", profile=worker_profile, label="worker decode")
    _require_benchmark(network_result, expected_name="tcp_network_path", profile=coordinator_profile, label="network result")

    artifact = _artifact(model_manifest, artifact_digest)
    model_name, model_size = _model_benchmark_consistency(
        artifact,
        [
            ("coordinator prefill", coordinator_prefill),
            ("coordinator decode", coordinator_decode),
            ("worker prefill", worker_prefill),
            ("worker decode", worker_decode),
        ],
    )
    if "contiguous_layers" not in model_manifest["partitioning"]["allowed"]:
        raise PlacementInputError("model manifest does not allow contiguous_layers partitioning")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    coordinator_age = _age_hours(coordinator_profile["captured_at"], current)
    worker_age = _age_hours(worker_profile["captured_at"], current)
    coordinator_memory = _usable_memory(coordinator_profile, policy)
    worker_memory = _usable_memory(worker_profile, policy)
    coordinator = {"node_id": coordinator_profile["node_id"], **coordinator_memory}
    worker = {"node_id": worker_profile["node_id"], **worker_memory}

    constraints = [
        _constraint("coordinator_not_draining", not coordinator_profile["provider_limits"]["draining"], "provider_limits.draining must be false"),
        _constraint("worker_not_draining", not worker_profile["provider_limits"]["draining"], "provider_limits.draining must be false"),
        _constraint("coordinator_profile_fresh", coordinator_age <= policy.max_profile_age_hours, f"age_hours={coordinator_age:.3f}"),
        _constraint("worker_profile_fresh", worker_age <= policy.max_profile_age_hours, f"age_hours={worker_age:.3f}"),
        _constraint("network_peer_assertion_matches_worker", True, "peer node binding is caller-asserted because benchmark_result v1 does not encode target node_id"),
    ]
    hard_ok = all(item["passed"] for item in constraints)

    local = _candidate_local(coordinator, model_size=model_size, layer_count=layer_count)
    shared = _candidate_shared(
        coordinator,
        worker,
        model_size=model_size,
        layer_count=layer_count,
        fixed_overhead_fraction=policy.fixed_model_overhead_fraction,
    )
    if not hard_ok:
        local["feasible"] = False
        local["layer_ranges"] = []
        local["tensor_split"] = []
        local["explanation"] = "hard node/profile constraints failed"
        shared["feasible"] = False
        shared["layer_ranges"] = []
        shared["tensor_split"] = []
        shared["explanation"] = "hard node/profile constraints failed"

    if shared["feasible"]:
        recommendation_mode = "shared_experiment"
        explanation = "shared placement is memory-feasible; run it as an experiment and compare against the local baseline before any production ranking"
    elif local["feasible"]:
        recommendation_mode = "local_only"
        explanation = "shared placement is not conservatively feasible; coordinator local placement remains feasible"
    else:
        recommendation_mode = "no_plan"
        explanation = "no candidate satisfies current hard constraints and conservative memory feasibility"

    performance = {
        "status": "insufficient_shared_runtime_evidence",
        "coordinator_prefill_tokens_per_second": _metric(coordinator_prefill, "prefill_tokens_per_second_avg"),
        "coordinator_decode_tokens_per_second": _metric(coordinator_decode, "decode_tokens_per_second_avg"),
        "worker_prefill_tokens_per_second": _metric(worker_prefill, "prefill_tokens_per_second_avg"),
        "worker_decode_tokens_per_second": _metric(worker_decode, "decode_tokens_per_second_avg"),
        "network_rtt_ms_p50": _metric(network_result, "rtt_ms_p50"),
        "network_rtt_ms_p95": _metric(network_result, "rtt_ms_p95"),
        "network_upload_mbps_p50": _metric(network_result, "upload_mbps_p50"),
        "network_download_mbps_p50": _metric(network_result, "download_mbps_p50"),
        "predicted_shared_request_ms": None,
        "predicted_speedup_vs_local": None,
        "reason": "individual compute and path benchmarks do not determine shared llama.cpp runtime cost without a correct measured shared run/transfer trace",
    }

    identity_material = {
        "model_digest": artifact["digest"],
        "layer_count": layer_count,
        "coordinator_node_id": coordinator_profile["node_id"],
        "coordinator_revision": coordinator_profile["profile_revision"],
        "worker_node_id": worker_profile["node_id"],
        "worker_revision": worker_profile["profile_revision"],
        "benchmark_run_ids": [
            coordinator_prefill["run_id"], coordinator_decode["run_id"],
            worker_prefill["run_id"], worker_decode["run_id"], network_result["run_id"],
        ],
        "policy": {
            "max_profile_age_hours": policy.max_profile_age_hours,
            "planner_memory_fraction": policy.planner_memory_fraction,
            "fixed_model_overhead_fraction": policy.fixed_model_overhead_fraction,
        },
    }
    canonical = json.dumps(identity_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    decision_id = f"placement-{hashlib.sha256(canonical).hexdigest()[:16]}"

    result = {
        "schema_version": 1,
        "decision_id": decision_id,
        "captured_at": current.isoformat().replace("+00:00", "Z"),
        "scope": "m1_two_node_llama_experiment",
        "model": {
            "model_id": model_manifest["model_id"],
            "model_version": model_manifest["model_version"],
            "artifact_digest": artifact["digest"],
            "artifact_size_bytes": model_size,
            "benchmark_model_name": model_name,
            "layer_count": layer_count,
        },
        "nodes": {
            "coordinator": {
                **coordinator,
                "profile_revision": coordinator_profile["profile_revision"],
                "profile_age_hours": round(coordinator_age, 6),
            },
            "worker": {
                **worker,
                "profile_revision": worker_profile["profile_revision"],
                "profile_age_hours": round(worker_age, 6),
            },
        },
        "network_evidence": {
            "run_id": network_result["run_id"],
            "peer_node_id": network_peer_node_id,
            "peer_binding": "caller_asserted_v1",
        },
        "hard_constraints": constraints,
        "candidates": [local, shared],
        "performance_evidence": performance,
        "recommendation": {
            "mode": recommendation_mode,
            "production_scheduling": False,
            "explanation": explanation,
        },
    }
    _validate(result, DECISION_SCHEMA, "placement decision")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh deterministic M1 two-node placement planner")
    parser.add_argument("--coordinator-profile", type=Path, required=True)
    parser.add_argument("--worker-profile", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--coordinator-prefill", type=Path, required=True)
    parser.add_argument("--coordinator-decode", type=Path, required=True)
    parser.add_argument("--worker-prefill", type=Path, required=True)
    parser.add_argument("--worker-decode", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--network-peer-node-id", required=True)
    parser.add_argument("--layer-count", type=int, required=True)
    parser.add_argument("--artifact-digest")
    parser.add_argument("--max-profile-age-hours", type=float, default=24.0)
    parser.add_argument("--planner-memory-fraction", type=float, default=0.90)
    parser.add_argument("--fixed-model-overhead-fraction", type=float, default=0.10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    policy = PlannerPolicy(
        max_profile_age_hours=args.max_profile_age_hours,
        planner_memory_fraction=args.planner_memory_fraction,
        fixed_model_overhead_fraction=args.fixed_model_overhead_fraction,
    )
    try:
        decision = build_placement_decision(
            coordinator_profile=_load_json(args.coordinator_profile),
            worker_profile=_load_json(args.worker_profile),
            model_manifest=_load_json(args.model_manifest),
            coordinator_prefill=_load_json(args.coordinator_prefill),
            coordinator_decode=_load_json(args.coordinator_decode),
            worker_prefill=_load_json(args.worker_prefill),
            worker_decode=_load_json(args.worker_decode),
            network_result=_load_json(args.network),
            network_peer_node_id=args.network_peer_node_id,
            layer_count=args.layer_count,
            artifact_digest=args.artifact_digest,
            policy=policy,
        )
    except (OSError, json.JSONDecodeError, PlacementInputError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
