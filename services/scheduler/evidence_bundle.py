#!/usr/bin/env python3
"""Build one fail-closed M1 placement evidence bundle from two lab exports.

This helper is deliberately narrower than the placement planner's compatibility
CLI. It accepts only current evidence that carries its own model layer count and
network node binding. Legacy caller-asserted peer/layer fallbacks are excluded.

The output contains source document digests and safe basenames, never absolute
local filesystem paths, plus the fully validated placement decision.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from services.scheduler.placement import (
    PlacementInputError,
    PlannerPolicy,
    build_placement_decision,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "protocol" / "schemas"
BUNDLE_SCHEMA = Path(__file__).with_name("experiment_bundle.schema.json")
MAX_DISCOVERY_FILES = 10_000
MAX_JSON_BYTES = 16 * 1024 * 1024
CURRENT_PEER_BINDING = "unauthenticated_server_report_v1"


class EvidenceBundleError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceDocument:
    path: Path
    value: dict[str, Any]
    sha256: str

    @property
    def file_name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class NodeEvidence:
    profile: EvidenceDocument
    prefill: EvidenceDocument
    decode: EvidenceDocument


@dataclass(frozen=True)
class SelectedEvidence:
    coordinator: NodeEvidence
    worker: NodeEvidence
    manifest: EvidenceDocument
    network: EvidenceDocument
    artifact: dict[str, Any]
    benchmark_model_name: str


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_schema(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"schema root must be an object: {path}")
    return value


def _validate_schema(value: dict[str, Any], schema_path: Path, label: str) -> None:
    validator = Draft202012Validator(_json_schema(schema_path), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.path) or "<root>"
        raise EvidenceBundleError(f"{label} invalid at {where}: {first.message}")


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise EvidenceBundleError(f"{label} has invalid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceBundleError(f"{label} timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _load_document(path: Path, *, label: str) -> EvidenceDocument:
    path = Path(path)
    if path.is_symlink():
        raise EvidenceBundleError(f"{label} must not be a symlink: {path.name}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise EvidenceBundleError(f"cannot stat {label}: {exc}") from exc
    if not 1 <= size <= MAX_JSON_BYTES:
        raise EvidenceBundleError(f"{label} must be between 1 byte and {MAX_JSON_BYTES} bytes")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceBundleError(f"cannot read {label}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceBundleError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceBundleError(f"{label} JSON root must be an object")
    return EvidenceDocument(path=path, value=value, sha256=hashlib.sha256(raw).hexdigest())


def _looks_like_profile(value: dict[str, Any]) -> bool:
    return {"node_id", "profile_revision", "platform", "provider_limits"}.issubset(value)


def _looks_like_benchmark(value: dict[str, Any]) -> bool:
    return {"run_id", "benchmark_name", "profile_revision", "metrics", "conditions"}.issubset(value)


def discover_evidence(root: Path) -> tuple[list[EvidenceDocument], list[EvidenceDocument]]:
    """Discover schema-valid profile/benchmark JSON below one explicit root.

    Unknown JSON documents (for example Lab Setup config) are ignored. Any JSON
    that looks like evidence but fails its contract is rejected so a corrupt
    newer file cannot silently make the selector fall back to older evidence.
    Symlink files are not followed.
    """
    root = Path(root)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise EvidenceBundleError(f"cannot resolve evidence root {root}: {exc}") from exc
    if not resolved_root.is_dir():
        raise EvidenceBundleError(f"evidence root is not a directory: {root}")

    candidates = sorted(resolved_root.rglob("*.json"), key=lambda path: path.as_posix())
    if len(candidates) > MAX_DISCOVERY_FILES:
        raise EvidenceBundleError(
            f"evidence root contains more than {MAX_DISCOVERY_FILES} JSON files"
        )

    profiles: list[EvidenceDocument] = []
    benchmarks: list[EvidenceDocument] = []
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise EvidenceBundleError(f"cannot resolve evidence file {path.name}: {exc}") from exc
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise EvidenceBundleError(f"evidence file escapes root: {path.name}") from exc
        document = _load_document(path, label=f"evidence file {path.name}")
        if _looks_like_profile(document.value):
            _validate_schema(
                document.value,
                SCHEMA_ROOT / "node_profile.schema.json",
                f"node profile {path.name}",
            )
            profiles.append(document)
        elif _looks_like_benchmark(document.value):
            _validate_schema(
                document.value,
                SCHEMA_ROOT / "benchmark_result.schema.json",
                f"benchmark {path.name}",
            )
            benchmarks.append(document)
    return profiles, benchmarks


def _select_current_profile(
    profiles: list[EvidenceDocument],
    *,
    role: str,
    requested_node_id: str | None,
) -> EvidenceDocument:
    if requested_node_id is not None:
        profiles = [doc for doc in profiles if doc.value["node_id"] == requested_node_id]
        if not profiles:
            raise EvidenceBundleError(f"{role} root has no profile for node_id {requested_node_id!r}")
    if not profiles:
        raise EvidenceBundleError(f"{role} root contains no node profile")

    node_ids = {str(doc.value["node_id"]) for doc in profiles}
    if len(node_ids) != 1:
        raise EvidenceBundleError(
            f"{role} root contains multiple node IDs {sorted(node_ids)}; use --{role}-node-id"
        )
    max_revision = max(int(doc.value["profile_revision"]) for doc in profiles)
    latest = [doc for doc in profiles if int(doc.value["profile_revision"]) == max_revision]
    canonical = {_canonical_json(doc.value) for doc in latest}
    if len(canonical) != 1:
        raise EvidenceBundleError(
            f"{role} root has conflicting profiles at revision {max_revision}"
        )
    return sorted(latest, key=lambda doc: (doc.file_name, doc.sha256))[0]


def _select_artifact(manifest: dict[str, Any], digest: str | None) -> dict[str, Any]:
    artifacts = manifest["artifacts"]
    if digest is None:
        if len(artifacts) != 1:
            raise EvidenceBundleError(
                "--artifact-digest is required when model manifest has multiple artifacts"
            )
        return artifacts[0]
    normalized = digest if digest.startswith("sha256:") else f"sha256:{digest}"
    matches = [artifact for artifact in artifacts if artifact["digest"] == normalized]
    if len(matches) != 1:
        raise EvidenceBundleError("selected artifact digest is not present exactly once in manifest")
    return matches[0]


def _eligible_llama(
    benchmarks: Iterable[EvidenceDocument],
    *,
    profile: EvidenceDocument,
    artifact_size: int,
) -> list[EvidenceDocument]:
    revision = int(profile.value["profile_revision"])
    profile_time = _timestamp(profile.value["captured_at"], "node profile")
    selected: list[EvidenceDocument] = []
    for doc in benchmarks:
        value = doc.value
        if value["benchmark_name"] not in {"llama_cpp_prefill", "llama_cpp_decode"}:
            continue
        if int(value["profile_revision"]) != revision:
            continue
        metrics = value.get("metrics", {})
        measured_size = metrics.get("model_size_bytes")
        model_name = metrics.get("model_name")
        if (
            isinstance(measured_size, bool)
            or not isinstance(measured_size, (int, float))
            or int(measured_size) != artifact_size
            or not isinstance(model_name, str)
            or not model_name
        ):
            continue
        if _timestamp(value["captured_at"], f"benchmark {value['run_id']}") < profile_time:
            continue
        selected.append(doc)
    return selected


def _complete_models(benchmarks: Iterable[EvidenceDocument]) -> set[str]:
    by_model: dict[str, set[str]] = {}
    for doc in benchmarks:
        model = str(doc.value["metrics"]["model_name"])
        by_model.setdefault(model, set()).add(str(doc.value["benchmark_name"]))
    required = {"llama_cpp_prefill", "llama_cpp_decode"}
    return {model for model, kinds in by_model.items() if required.issubset(kinds)}


def _latest_unique(
    documents: Iterable[EvidenceDocument],
    *,
    label: str,
) -> EvidenceDocument:
    docs = list(documents)
    if not docs:
        raise EvidenceBundleError(f"no matching {label}")
    timestamps = [(_timestamp(doc.value["captured_at"], label), doc) for doc in docs]
    newest = max(timestamp for timestamp, _ in timestamps)
    latest = [doc for timestamp, doc in timestamps if timestamp == newest]
    unique_content = {(doc.value.get("run_id"), doc.sha256) for doc in latest}
    if len(unique_content) != 1:
        run_ids = sorted(str(doc.value.get("run_id")) for doc in latest)
        raise EvidenceBundleError(
            f"ambiguous equally recent {label} candidates: {run_ids}"
        )
    return sorted(latest, key=lambda doc: (str(doc.value.get("run_id")), doc.sha256))[0]


def _select_llama_pair(
    benchmarks: list[EvidenceDocument],
    *,
    model_name: str,
    role: str,
) -> tuple[EvidenceDocument, EvidenceDocument]:
    relevant = [doc for doc in benchmarks if doc.value["metrics"]["model_name"] == model_name]
    prefill = _latest_unique(
        (doc for doc in relevant if doc.value["benchmark_name"] == "llama_cpp_prefill"),
        label=f"{role} prefill",
    )
    decode = _latest_unique(
        (doc for doc in relevant if doc.value["benchmark_name"] == "llama_cpp_decode"),
        label=f"{role} decode",
    )
    return prefill, decode


def _select_network(
    benchmarks: list[EvidenceDocument],
    *,
    coordinator_profile: EvidenceDocument,
    worker_profile: EvidenceDocument,
    requested_run_id: str | None,
) -> EvidenceDocument:
    coordinator = coordinator_profile.value
    worker = worker_profile.value
    profile_time = _timestamp(coordinator["captured_at"], "coordinator profile")
    eligible: list[EvidenceDocument] = []
    for doc in benchmarks:
        value = doc.value
        if value["benchmark_name"] != "tcp_network_path":
            continue
        if int(value["profile_revision"]) != int(coordinator["profile_revision"]):
            continue
        conditions = value.get("conditions", {})
        if conditions.get("local_node_id") != coordinator["node_id"]:
            continue
        if conditions.get("peer_node_id") != worker["node_id"]:
            continue
        binding = conditions.get("peer_identity_binding")
        if not isinstance(binding, str) or not binding:
            continue
        if _timestamp(value["captured_at"], f"network benchmark {value['run_id']}") < profile_time:
            continue
        if requested_run_id is not None and value["run_id"] != requested_run_id:
            continue
        eligible.append(doc)
    if requested_run_id is not None and not eligible:
        raise EvidenceBundleError(
            f"network run {requested_run_id!r} is absent or does not bind coordinator→worker"
        )
    return _latest_unique(eligible, label="coordinator→worker network benchmark")


def select_evidence(
    *,
    coordinator_root: Path,
    worker_root: Path,
    model_manifest: Path,
    artifact_digest: str | None = None,
    coordinator_node_id: str | None = None,
    worker_node_id: str | None = None,
    benchmark_model_name: str | None = None,
    network_run_id: str | None = None,
) -> SelectedEvidence:
    manifest_doc = _load_document(Path(model_manifest), label="model manifest")
    _validate_schema(
        manifest_doc.value,
        SCHEMA_ROOT / "model_manifest.schema.json",
        "model manifest",
    )
    layer_count = manifest_doc.value.get("layer_count")
    if isinstance(layer_count, bool) or not isinstance(layer_count, int):
        raise EvidenceBundleError(
            "current experiment bundle requires model_manifest.layer_count; legacy caller fallback is not allowed"
        )
    artifact = _select_artifact(manifest_doc.value, artifact_digest)
    artifact_size = int(artifact["size_bytes"])

    coordinator_profiles, coordinator_benchmarks = discover_evidence(coordinator_root)
    worker_profiles, worker_benchmarks = discover_evidence(worker_root)
    coordinator_profile = _select_current_profile(
        coordinator_profiles,
        role="coordinator",
        requested_node_id=coordinator_node_id,
    )
    worker_profile = _select_current_profile(
        worker_profiles,
        role="worker",
        requested_node_id=worker_node_id,
    )
    if coordinator_profile.value["node_id"] == worker_profile.value["node_id"]:
        raise EvidenceBundleError("coordinator and worker roots resolve to the same node_id")

    coordinator_llama = _eligible_llama(
        coordinator_benchmarks,
        profile=coordinator_profile,
        artifact_size=artifact_size,
    )
    worker_llama = _eligible_llama(
        worker_benchmarks,
        profile=worker_profile,
        artifact_size=artifact_size,
    )
    common_models = _complete_models(coordinator_llama) & _complete_models(worker_llama)
    if benchmark_model_name is not None:
        if benchmark_model_name not in common_models:
            raise EvidenceBundleError(
                f"requested benchmark model {benchmark_model_name!r} has no complete matching evidence on both nodes"
            )
        selected_model = benchmark_model_name
    else:
        if not common_models:
            raise EvidenceBundleError(
                "no common model basename has matching prefill/decode evidence on both current profiles"
            )
        if len(common_models) != 1:
            raise EvidenceBundleError(
                "multiple common model basenames match the manifest artifact size; "
                f"use --benchmark-model-name: {sorted(common_models)}"
            )
        selected_model = next(iter(common_models))

    coordinator_prefill, coordinator_decode = _select_llama_pair(
        coordinator_llama,
        model_name=selected_model,
        role="coordinator",
    )
    worker_prefill, worker_decode = _select_llama_pair(
        worker_llama,
        model_name=selected_model,
        role="worker",
    )
    network = _select_network(
        coordinator_benchmarks,
        coordinator_profile=coordinator_profile,
        worker_profile=worker_profile,
        requested_run_id=network_run_id,
    )
    return SelectedEvidence(
        coordinator=NodeEvidence(
            profile=coordinator_profile,
            prefill=coordinator_prefill,
            decode=coordinator_decode,
        ),
        worker=NodeEvidence(
            profile=worker_profile,
            prefill=worker_prefill,
            decode=worker_decode,
        ),
        manifest=manifest_doc,
        network=network,
        artifact=artifact,
        benchmark_model_name=selected_model,
    )


def _source(doc: EvidenceDocument, *, extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_name": doc.file_name,
        "document_sha256": f"sha256:{doc.sha256}",
        **extra,
    }


def build_experiment_bundle(
    selected: SelectedEvidence,
    *,
    policy: PlannerPolicy = PlannerPolicy(),
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    decision = build_placement_decision(
        coordinator_profile=selected.coordinator.profile.value,
        worker_profile=selected.worker.profile.value,
        model_manifest=selected.manifest.value,
        coordinator_prefill=selected.coordinator.prefill.value,
        coordinator_decode=selected.coordinator.decode.value,
        worker_prefill=selected.worker.prefill.value,
        worker_decode=selected.worker.decode.value,
        network_result=selected.network.value,
        artifact_digest=selected.artifact["digest"],
        policy=policy,
        now=current,
    )
    if decision["model"]["layer_count_source"] != "model_manifest_v1":
        raise EvidenceBundleError("bundle unexpectedly used a legacy layer-count fallback")
    if decision["network_evidence"]["peer_binding"] == "caller_asserted_v1":
        raise EvidenceBundleError("bundle unexpectedly used a legacy network-peer fallback")

    coordinator = selected.coordinator.profile.value
    worker = selected.worker.profile.value
    network = selected.network.value
    manifest = selected.manifest.value
    sources = {
        "model_manifest": _source(
            selected.manifest,
            extra={
                "model_id": manifest["model_id"],
                "model_version": manifest["model_version"],
                "artifact_digest": selected.artifact["digest"],
                "artifact_size_bytes": int(selected.artifact["size_bytes"]),
                "layer_count": int(manifest["layer_count"]),
            },
        ),
        "coordinator": {
            "profile": _source(
                selected.coordinator.profile,
                extra={
                    "node_id": coordinator["node_id"],
                    "profile_revision": int(coordinator["profile_revision"]),
                },
            ),
            "prefill": _source(
                selected.coordinator.prefill,
                extra={"run_id": selected.coordinator.prefill.value["run_id"]},
            ),
            "decode": _source(
                selected.coordinator.decode,
                extra={"run_id": selected.coordinator.decode.value["run_id"]},
            ),
        },
        "worker": {
            "profile": _source(
                selected.worker.profile,
                extra={
                    "node_id": worker["node_id"],
                    "profile_revision": int(worker["profile_revision"]),
                },
            ),
            "prefill": _source(
                selected.worker.prefill,
                extra={"run_id": selected.worker.prefill.value["run_id"]},
            ),
            "decode": _source(
                selected.worker.decode,
                extra={"run_id": selected.worker.decode.value["run_id"]},
            ),
        },
        "network": _source(
            selected.network,
            extra={
                "run_id": network["run_id"],
                "local_node_id": network["conditions"]["local_node_id"],
                "peer_node_id": network["conditions"]["peer_node_id"],
                "peer_identity_binding": network["conditions"]["peer_identity_binding"],
            },
        ),
    }
    identity = {
        "decision_id": decision["decision_id"],
        "source_sha256": sorted(
            [
                selected.manifest.sha256,
                selected.coordinator.profile.sha256,
                selected.coordinator.prefill.sha256,
                selected.coordinator.decode.sha256,
                selected.worker.profile.sha256,
                selected.worker.prefill.sha256,
                selected.worker.decode.sha256,
                selected.network.sha256,
            ]
        ),
    }
    bundle_id = "experiment-bundle-" + hashlib.sha256(_canonical_json(identity)).hexdigest()[:16]
    bundle = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "captured_at": current.isoformat().replace("+00:00", "Z"),
        "scope": "m1_two_node_placement_evidence",
        "benchmark_model_name": selected.benchmark_model_name,
        "sources": sources,
        "placement_decision": decision,
    }
    _validate_schema(bundle, BUNDLE_SCHEMA, "experiment bundle")
    return bundle


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind two current Lab evidence exports into one M1 placement bundle"
    )
    parser.add_argument("--coordinator-root", type=Path, required=True)
    parser.add_argument("--worker-root", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--artifact-digest")
    parser.add_argument("--coordinator-node-id")
    parser.add_argument("--worker-node-id")
    parser.add_argument("--benchmark-model-name")
    parser.add_argument("--network-run-id")
    parser.add_argument("--max-profile-age-hours", type=float, default=24.0)
    parser.add_argument("--planner-memory-fraction", type=float, default=0.90)
    parser.add_argument("--fixed-model-overhead-fraction", type=float, default=0.10)
    parser.add_argument("--max-future-skew-minutes", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        policy = PlannerPolicy(
            max_profile_age_hours=args.max_profile_age_hours,
            planner_memory_fraction=args.planner_memory_fraction,
            fixed_model_overhead_fraction=args.fixed_model_overhead_fraction,
            max_future_skew_minutes=args.max_future_skew_minutes,
        )
        selected = select_evidence(
            coordinator_root=args.coordinator_root,
            worker_root=args.worker_root,
            model_manifest=args.model_manifest,
            artifact_digest=args.artifact_digest,
            coordinator_node_id=args.coordinator_node_id,
            worker_node_id=args.worker_node_id,
            benchmark_model_name=args.benchmark_model_name,
            network_run_id=args.network_run_id,
        )
        bundle = build_experiment_bundle(selected, policy=policy)
        write_json(args.output, bundle)
    except (OSError, json.JSONDecodeError, EvidenceBundleError, PlacementInputError, ValueError) as exc:
        parser.error(str(exc))
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
