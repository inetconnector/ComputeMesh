#!/usr/bin/env python3
"""Deterministic two-node feasibility planner for the narrow M1 llama.cpp experiment.

This reference planner deliberately separates feasibility from performance
claims. It consumes measured node profiles, llama-bench results, a network
benchmark and a model manifest. New evidence can carry the network peer and
model layer count directly; explicit caller assertions remain a legacy fallback.
Until a correct shared runtime result exists it never predicts or claims shared
latency/speedup.
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
    max_future_skew_minutes: float = 5.0

    def __post_init__(self) -> None:
        if not 0 < self.max_profile_age_hours <= 720:
            raise ValueError("max_profile_age_hours must be >0 and <=720")
        if not 0 < self.planner_memory_fraction <= 1:
            raise ValueError("planner_memory_fraction must be >0 and <=1")
        if not 0 <= self.fixed_model_overhead_fraction < 0.5:
            raise ValueError("fixed_model_overhead_fraction must be >=0 and <0.5")
        if not 0 <= self.max_future_skew_minutes <= 60:
            raise ValueError("max_future_skew_minutes must be between 0 and 60")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlacementInputError(f"{path}: JSON root must be an object")
    return value


def _schema(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid schema {path}")
    return value


def _validate(value: dict[str, Any], schema_path: Path, label: str) -> None:
    validator = Draft202012Validator(_schema(schema_path), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        where = ".".join(str(part) for part in error.path) or "<root>"
        raise PlacementInputError(f"{label} invalid at {where}: {error.message}")


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlacementInputError("invalid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise PlacementInputError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _profile_clock(value: str, now: datetime) -> tuple[float, float]:
    delta_hours = (now - _timestamp(value)).total_seconds() / 3600.0
    return max(0.0, delta_hours), max(0.0, -delta_hours * 60.0)


def _positive_metric(result: dict[str, Any], key: str) -> float:
    value = result.get("metrics", {}).get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise PlacementInputError(f"benchmark metric {key!r} must be positive")
    return float(value)


def _selected_memory(profile: dict[str, Any], policy: PlannerPolicy) -> dict[str, Any]:
    accelerators = [
        device for device in profile["devices"]
        if device["kind"] in {"gpu", "accelerator"} and int(device["memory_total_bytes"]) > 0
    ]
    if accelerators:
        selected = sorted(
            accelerators,
            key=lambda device: (-int(device["memory_total_bytes"]), device["device_id"]),
        )[0]
        device_id = selected["device_id"]
        kind = selected["kind"]
        name = selected["name"]
        raw = int(selected["memory_total_bytes"])
    else:
        device_id = "cpu:system-memory"
        kind = "cpu"
        name = profile["cpu"].get("model") or "CPU"
        raw = int(profile["memory"]["available_bytes"])

    provider_fraction = profile["provider_limits"].get("max_memory_fraction", 1.0)
    if isinstance(provider_fraction, bool) or not isinstance(provider_fraction, (int, float)):
        provider_fraction = 1.0
    effective = min(float(provider_fraction), policy.planner_memory_fraction)
    return {
        "device_id": device_id,
        "kind": kind,
        "name": name,
        "raw_memory_bytes": raw,
        "provider_memory_fraction": float(provider_fraction),
        "planner_memory_fraction": policy.planner_memory_fraction,
        "effective_memory_fraction": effective,
        "usable_memory_bytes": math.floor(raw * effective),
    }


def _require_benchmark(result: dict[str, Any], name: str, profile: dict[str, Any], label: str) -> None:
    if result["benchmark_name"] != name:
        raise PlacementInputError(f"{label} must be {name}")
    if int(result["profile_revision"]) != int(profile["profile_revision"]):
        raise PlacementInputError(f"{label} profile revision does not match node profile")


def _select_artifact(manifest: dict[str, Any], digest: str | None) -> dict[str, Any]:
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


def _same_benchmark_model(
    artifact: dict[str, Any],
    labelled: list[tuple[str, dict[str, Any]]],
) -> tuple[str, int]:
    size = int(artifact["size_bytes"])
    names: set[str] = set()
    for label, result in labelled:
        measured_size = result["metrics"].get("model_size_bytes")
        name = result["metrics"].get("model_name")
        if (
            isinstance(measured_size, bool)
            or not isinstance(measured_size, (int, float))
            or int(measured_size) != size
        ):
            raise PlacementInputError(
                f"{label} model_size_bytes does not match selected manifest artifact"
            )
        if not isinstance(name, str) or not name:
            raise PlacementInputError(f"{label} missing model_name")
        names.add(name)
    if len(names) != 1:
        raise PlacementInputError("llama benchmarks do not refer to the same model basename")
    return next(iter(names)), size


def _resolve_layer_count(
    manifest: dict[str, Any],
    caller_layer_count: int | None,
) -> tuple[int, str]:
    manifest_layer_count = manifest.get("layer_count")
    if caller_layer_count is not None:
        if (
            isinstance(caller_layer_count, bool)
            or not isinstance(caller_layer_count, int)
            or not 2 <= caller_layer_count <= 100_000
        ):
            raise PlacementInputError("layer_count must be an integer between 2 and 100000")
    if manifest_layer_count is not None:
        resolved = int(manifest_layer_count)
        if caller_layer_count is not None and caller_layer_count != resolved:
            raise PlacementInputError("caller layer_count does not match model manifest layer_count")
        return resolved, "model_manifest_v1"
    if caller_layer_count is None:
        raise PlacementInputError(
            "layer_count is required when the model manifest does not contain layer_count"
        )
    return caller_layer_count, "caller_asserted_v1"


def _resolve_network_binding(
    network_result: dict[str, Any],
    coordinator_node_id: str,
    worker_node_id: str,
    caller_peer_node_id: str | None,
) -> tuple[str, str, list[dict[str, Any]]]:
    if caller_peer_node_id is not None:
        if (
            not isinstance(caller_peer_node_id, str)
            or not caller_peer_node_id
            or len(caller_peer_node_id) > 128
        ):
            raise PlacementInputError("network_peer_node_id must be 1..128 characters")

    conditions = network_result.get("conditions", {})
    local_node_id = conditions.get("local_node_id")
    measured_peer_node_id = conditions.get("peer_node_id")
    measured_binding = conditions.get("peer_identity_binding")

    constraints: list[dict[str, Any]] = []
    if local_node_id is not None:
        if local_node_id != coordinator_node_id:
            raise PlacementInputError(
                "network benchmark local_node_id does not match coordinator profile"
            )
        constraints.append(_constraint(
            "network_local_node_matches_coordinator",
            True,
            "benchmark conditions.local_node_id matches coordinator profile",
        ))
    else:
        constraints.append(_constraint(
            "network_local_node_matches_coordinator",
            True,
            "legacy benchmark has no local_node_id; coordinator binding relies on supplied record plus profile_revision",
        ))

    if measured_peer_node_id is not None:
        if measured_peer_node_id != worker_node_id:
            raise PlacementInputError(
                "network benchmark peer_node_id does not match worker profile"
            )
        if caller_peer_node_id is not None and caller_peer_node_id != measured_peer_node_id:
            raise PlacementInputError(
                "caller network peer node_id conflicts with benchmark peer_node_id"
            )
        binding = str(measured_binding)
        constraints.append(_constraint(
            "network_peer_matches_worker",
            True,
            f"benchmark peer_node_id matches worker; binding={binding}",
        ))
        return measured_peer_node_id, binding, constraints

    if caller_peer_node_id is None:
        raise PlacementInputError(
            "network peer identity is absent; provide network_peer_node_id for a legacy benchmark"
        )
    if caller_peer_node_id != worker_node_id:
        raise PlacementInputError(
            "caller-asserted network peer node_id does not match worker profile"
        )
    constraints.append(_constraint(
        "network_peer_matches_worker",
        True,
        "legacy peer binding is caller-asserted because the benchmark record has no peer_node_id",
    ))
    return caller_peer_node_id, "caller_asserted_v1", constraints


def _constraint(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail[:512]}


def _local_candidate(node: dict[str, Any], model_size: int, layer_count: int) -> dict[str, Any]:
    feasible = node["usable_memory_bytes"] >= model_size
    return {
        "mode": "local_only",
        "feasible": feasible,
        "layer_ranges": [{
            "node_id": node["node_id"],
            "start_layer": 0,
            "end_layer_exclusive": layer_count,
        }] if feasible else [],
        "tensor_split": [1.0] if feasible else [],
        "explanation": (
            "selected coordinator memory budget can hold the complete artifact"
            if feasible
            else "selected coordinator memory budget cannot hold the complete artifact"
        ),
    }


def _shared_candidate(
    coordinator: dict[str, Any],
    worker: dict[str, Any],
    model_size: int,
    layer_count: int,
    overhead_fraction: float,
) -> dict[str, Any]:
    fixed = math.ceil(model_size * overhead_fraction)
    per_layer = max(1, math.ceil(max(1, model_size - fixed) / layer_count))
    coord_max = min(
        layer_count,
        max(0, coordinator["usable_memory_bytes"] - fixed) // per_layer,
    )
    worker_max = min(layer_count, worker["usable_memory_bytes"] // per_layer)
    memory_model = {
        "fixed_coordinator_bytes": fixed,
        "estimated_layer_bytes": per_layer,
        "coordinator_max_layers": int(coord_max),
        "worker_max_layers": int(worker_max),
    }
    feasible = coord_max >= 1 and worker_max >= 1 and coord_max + worker_max >= layer_count
    if not feasible:
        return {
            "mode": "shared_contiguous_layers",
            "feasible": False,
            "layer_ranges": [],
            "tensor_split": [],
            "memory_model": memory_model,
            "explanation": "combined conservative layer budgets cannot place at least one layer on each node",
        }

    total_capacity = coord_max + worker_max
    worker_layers = max(1, round(layer_count * worker_max / total_capacity))
    worker_layers = min(worker_layers, worker_max, layer_count - 1)
    coord_layers = layer_count - worker_layers
    if coord_layers > coord_max:
        shift = coord_layers - coord_max
        coord_layers -= shift
        worker_layers += shift
    if coord_layers < 1 or worker_layers > worker_max:
        raise RuntimeError("internal placement calculation exceeded memory bounds")
    return {
        "mode": "shared_contiguous_layers",
        "feasible": True,
        "layer_ranges": [
            {
                "node_id": coordinator["node_id"],
                "start_layer": 0,
                "end_layer_exclusive": int(coord_layers),
            },
            {
                "node_id": worker["node_id"],
                "start_layer": int(coord_layers),
                "end_layer_exclusive": layer_count,
            },
        ],
        "tensor_split": [float(coord_layers), float(worker_layers)],
        "memory_model": memory_model,
        "explanation": "contiguous two-node candidate derived from conservative selected-device memory budgets only",
    }


def _disable(candidate: dict[str, Any], reason: str) -> None:
    candidate["feasible"] = False
    candidate["layer_ranges"] = []
    candidate["tensor_split"] = []
    candidate["explanation"] = reason


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
    network_peer_node_id: str | None = None,
    layer_count: int | None = None,
    artifact_digest: str | None = None,
    policy: PlannerPolicy = PlannerPolicy(),
    now: datetime | None = None,
) -> dict[str, Any]:
    documents = (
        (coordinator_profile, "node_profile.schema.json", "coordinator profile"),
        (worker_profile, "node_profile.schema.json", "worker profile"),
        (model_manifest, "model_manifest.schema.json", "model manifest"),
        (coordinator_prefill, "benchmark_result.schema.json", "coordinator prefill"),
        (coordinator_decode, "benchmark_result.schema.json", "coordinator decode"),
        (worker_prefill, "benchmark_result.schema.json", "worker prefill"),
        (worker_decode, "benchmark_result.schema.json", "worker decode"),
        (network_result, "benchmark_result.schema.json", "network result"),
    )
    for value, schema_name, label in documents:
        _validate(value, SCHEMA_ROOT / schema_name, label)

    if coordinator_profile["node_id"] == worker_profile["node_id"]:
        raise PlacementInputError("coordinator and worker must have different node_id values")

    resolved_layer_count, layer_count_source = _resolve_layer_count(
        model_manifest,
        layer_count,
    )
    peer_node_id, peer_binding, network_constraints = _resolve_network_binding(
        network_result,
        coordinator_profile["node_id"],
        worker_profile["node_id"],
        network_peer_node_id,
    )

    _require_benchmark(
        coordinator_prefill,
        "llama_cpp_prefill",
        coordinator_profile,
        "coordinator prefill",
    )
    _require_benchmark(
        coordinator_decode,
        "llama_cpp_decode",
        coordinator_profile,
        "coordinator decode",
    )
    _require_benchmark(worker_prefill, "llama_cpp_prefill", worker_profile, "worker prefill")
    _require_benchmark(worker_decode, "llama_cpp_decode", worker_profile, "worker decode")
    _require_benchmark(network_result, "tcp_network_path", coordinator_profile, "network result")

    artifact = _select_artifact(model_manifest, artifact_digest)
    model_name, model_size = _same_benchmark_model(
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
    coord_age, coord_future = _profile_clock(coordinator_profile["captured_at"], current)
    worker_age, worker_future = _profile_clock(worker_profile["captured_at"], current)
    coord_mem = _selected_memory(coordinator_profile, policy)
    worker_mem = _selected_memory(worker_profile, policy)
    coordinator = {"node_id": coordinator_profile["node_id"], **coord_mem}
    worker = {"node_id": worker_profile["node_id"], **worker_mem}

    coord_not_draining = not coordinator_profile["provider_limits"]["draining"]
    worker_not_draining = not worker_profile["provider_limits"]["draining"]
    coord_fresh = (
        coord_age <= policy.max_profile_age_hours
        and coord_future <= policy.max_future_skew_minutes
    )
    worker_fresh = (
        worker_age <= policy.max_profile_age_hours
        and worker_future <= policy.max_future_skew_minutes
    )
    constraints = [
        _constraint(
            "coordinator_not_draining",
            coord_not_draining,
            "provider_limits.draining must be false",
        ),
        _constraint(
            "worker_not_draining",
            worker_not_draining,
            "provider_limits.draining must be false for shared placement",
        ),
        _constraint(
            "coordinator_profile_fresh",
            coord_fresh,
            f"age_hours={coord_age:.3f}; future_skew_minutes={coord_future:.3f}",
        ),
        _constraint(
            "worker_profile_fresh",
            worker_fresh,
            f"age_hours={worker_age:.3f}; future_skew_minutes={worker_future:.3f}",
        ),
        *network_constraints,
    ]

    local = _local_candidate(coordinator, model_size, resolved_layer_count)
    shared = _shared_candidate(
        coordinator,
        worker,
        model_size,
        resolved_layer_count,
        policy.fixed_model_overhead_fraction,
    )
    coordinator_ok = coord_not_draining and coord_fresh
    worker_ok = worker_not_draining and worker_fresh
    if not coordinator_ok:
        _disable(local, "coordinator hard constraints failed")
        _disable(shared, "coordinator hard constraints failed")
    elif not worker_ok:
        _disable(shared, "worker hard constraints failed")

    if shared["feasible"]:
        mode = "shared_experiment"
        explanation = (
            "shared placement is memory-feasible; execute it only as an experiment and compare "
            "with local baseline before any production ranking"
        )
    elif local["feasible"]:
        mode = "local_only"
        explanation = (
            "shared placement is unavailable under current hard/memory constraints; "
            "coordinator local baseline remains feasible"
        )
    else:
        mode = "no_plan"
        explanation = (
            "no candidate satisfies current hard constraints and conservative memory feasibility"
        )

    performance = {
        "status": "insufficient_shared_runtime_evidence",
        "coordinator_prefill_tokens_per_second": _positive_metric(
            coordinator_prefill, "prefill_tokens_per_second_avg"
        ),
        "coordinator_decode_tokens_per_second": _positive_metric(
            coordinator_decode, "decode_tokens_per_second_avg"
        ),
        "worker_prefill_tokens_per_second": _positive_metric(
            worker_prefill, "prefill_tokens_per_second_avg"
        ),
        "worker_decode_tokens_per_second": _positive_metric(
            worker_decode, "decode_tokens_per_second_avg"
        ),
        "network_rtt_ms_p50": _positive_metric(network_result, "rtt_ms_p50"),
        "network_rtt_ms_p95": _positive_metric(network_result, "rtt_ms_p95"),
        "network_upload_mbps_p50": _positive_metric(network_result, "upload_mbps_p50"),
        "network_download_mbps_p50": _positive_metric(
            network_result, "download_mbps_p50"
        ),
        "predicted_shared_request_ms": None,
        "predicted_speedup_vs_local": None,
        "reason": (
            "individual compute/path benchmarks do not determine shared llama.cpp cost without "
            "a correct measured shared run and transfer trace"
        ),
    }

    identity = {
        "model_digest": artifact["digest"],
        "layer_count": resolved_layer_count,
        "layer_count_source": layer_count_source,
        "coordinator_node_id": coordinator_profile["node_id"],
        "coordinator_revision": coordinator_profile["profile_revision"],
        "worker_node_id": worker_profile["node_id"],
        "worker_revision": worker_profile["profile_revision"],
        "network_peer_binding": peer_binding,
        "benchmark_run_ids": [
            coordinator_prefill["run_id"],
            coordinator_decode["run_id"],
            worker_prefill["run_id"],
            worker_decode["run_id"],
            network_result["run_id"],
        ],
        "policy": {
            "max_profile_age_hours": policy.max_profile_age_hours,
            "planner_memory_fraction": policy.planner_memory_fraction,
            "fixed_model_overhead_fraction": policy.fixed_model_overhead_fraction,
            "max_future_skew_minutes": policy.max_future_skew_minutes,
        },
    }
    decision_id = "placement-" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]

    decision = {
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
            "layer_count": resolved_layer_count,
            "layer_count_source": layer_count_source,
        },
        "nodes": {
            "coordinator": {
                **coordinator,
                "profile_revision": coordinator_profile["profile_revision"],
                "profile_age_hours": round(coord_age, 6),
            },
            "worker": {
                **worker,
                "profile_revision": worker_profile["profile_revision"],
                "profile_age_hours": round(worker_age, 6),
            },
        },
        "network_evidence": {
            "run_id": network_result["run_id"],
            "peer_node_id": peer_node_id,
            "peer_binding": peer_binding,
        },
        "hard_constraints": constraints,
        "candidates": [local, shared],
        "performance_evidence": performance,
        "recommendation": {
            "mode": mode,
            "production_scheduling": False,
            "explanation": explanation,
        },
    }
    _validate(decision, DECISION_SCHEMA, "placement decision")
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ComputeMesh deterministic M1 two-node placement planner"
    )
    for option in (
        "coordinator-profile",
        "worker-profile",
        "model-manifest",
        "coordinator-prefill",
        "coordinator-decode",
        "worker-prefill",
        "worker-decode",
        "network",
    ):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument(
        "--network-peer-node-id",
        help="legacy fallback when the network benchmark has no peer_node_id",
    )
    parser.add_argument(
        "--layer-count",
        type=int,
        help="legacy fallback when the model manifest has no layer_count",
    )
    parser.add_argument("--artifact-digest")
    parser.add_argument("--max-profile-age-hours", type=float, default=24.0)
    parser.add_argument("--planner-memory-fraction", type=float, default=0.90)
    parser.add_argument("--fixed-model-overhead-fraction", type=float, default=0.10)
    parser.add_argument("--max-future-skew-minutes", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    policy = PlannerPolicy(
        max_profile_age_hours=args.max_profile_age_hours,
        planner_memory_fraction=args.planner_memory_fraction,
        fixed_model_overhead_fraction=args.fixed_model_overhead_fraction,
        max_future_skew_minutes=args.max_future_skew_minutes,
    )
    try:
        decision = build_placement_decision(
            coordinator_profile=_read_json(args.coordinator_profile),
            worker_profile=_read_json(args.worker_profile),
            model_manifest=_read_json(args.model_manifest),
            coordinator_prefill=_read_json(args.coordinator_prefill),
            coordinator_decode=_read_json(args.coordinator_decode),
            worker_prefill=_read_json(args.worker_prefill),
            worker_decode=_read_json(args.worker_decode),
            network_result=_read_json(args.network),
            network_peer_node_id=args.network_peer_node_id,
            layer_count=args.layer_count,
            artifact_digest=args.artifact_digest,
            policy=policy,
        )
    except (OSError, json.JSONDecodeError, PlacementInputError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
