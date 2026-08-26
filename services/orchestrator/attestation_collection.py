"""Control-plane collection of execution attestations from selected provider nodes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Protocol

MAX_REQUEST_BYTES = 1024 * 1024


class AttestationCollectionError(RuntimeError):
    pass


class NodeAttestationTransport(Protocol):
    def request_execution_attestation(
        self,
        *,
        node_id: str,
        request_document: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CollectionResult:
    job_id: str
    request_id: str
    participant_node_ids: tuple[str, ...]
    bundle_path: Path


def _load_request(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not (0 < path.stat().st_size <= MAX_REQUEST_BYTES):
        raise AttestationCollectionError("attestation request must be a bounded regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AttestationCollectionError("attestation request must contain UTF-8 JSON") from exc
    required = {
        "schema_version", "request_id", "job_id", "placement_decision_id", "model_sha256",
        "runtime_sha256", "evidence_sha256", "output_sha256", "expected_nodes",
    }
    if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != 1:
        raise AttestationCollectionError("invalid attestation request envelope")
    nodes = value.get("expected_nodes")
    if not isinstance(nodes, list) or len(nodes) < 2 or len(set(nodes)) != len(nodes):
        raise AttestationCollectionError("attestation request participant set is invalid")
    if any(not isinstance(node, str) or not node for node in nodes):
        raise AttestationCollectionError("attestation request contains an invalid node id")
    return value


def _validate_response(node_id: str, request: dict[str, Any], attestation: Any) -> dict[str, Any]:
    if not isinstance(attestation, dict):
        raise AttestationCollectionError(f"node {node_id} returned a non-object attestation")
    expected_fields = {
        "v", "node_id", "key_id", "job_id", "placement_decision_id", "model_sha256",
        "runtime_sha256", "evidence_sha256", "output_sha256", "issued_at", "expires_at", "signature",
    }
    if set(attestation) != expected_fields or attestation.get("v") != 1:
        raise AttestationCollectionError(f"node {node_id} returned an invalid attestation envelope")
    if attestation.get("node_id") != node_id:
        raise AttestationCollectionError(f"node {node_id} returned an attestation for another node")
    for field in (
        "job_id", "placement_decision_id", "model_sha256", "runtime_sha256", "evidence_sha256", "output_sha256"
    ):
        if attestation.get(field) != request[field]:
            raise AttestationCollectionError(f"node {node_id} attestation changed bound field {field}")
    return attestation


def collect_execution_attestations(
    *,
    request_path: Path,
    output_path: Path,
    transport: NodeAttestationTransport,
    per_node_timeout_seconds: float = 15.0,
) -> CollectionResult:
    """Request one signature from every selected node and atomically persist the bundle.

    The collector never degrades to a partial participant set. Cryptographic
    verification remains at the gateway settlement boundary; this layer ensures
    the transport responses preserve the exact public request claims.
    """
    if per_node_timeout_seconds <= 0 or per_node_timeout_seconds > 300:
        raise ValueError("per_node_timeout_seconds must be within (0, 300]")
    if output_path.exists():
        raise AttestationCollectionError("attestation bundle output already exists")
    request = _load_request(request_path)
    expected_nodes = tuple(request["expected_nodes"])
    responses: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=len(expected_nodes), thread_name_prefix="attestation") as pool:
        futures = {
            node_id: pool.submit(
                transport.request_execution_attestation,
                node_id=node_id,
                request_document=dict(request),
                timeout_seconds=per_node_timeout_seconds,
            )
            for node_id in expected_nodes
        }
        for node_id in expected_nodes:
            try:
                response = futures[node_id].result(timeout=per_node_timeout_seconds)
            except FutureTimeout as exc:
                for future in futures.values():
                    future.cancel()
                raise AttestationCollectionError(f"node {node_id} attestation request timed out") from exc
            except Exception as exc:
                for future in futures.values():
                    future.cancel()
                raise AttestationCollectionError(f"node {node_id} attestation request failed") from exc
            responses[node_id] = _validate_response(node_id, request, response)

    if set(responses) != set(expected_nodes):
        raise AttestationCollectionError("not all selected nodes returned an attestation")
    bundle = {
        "schema_version": 1,
        "attestations": [responses[node_id] for node_id in expected_nodes],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temp_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return CollectionResult(
        job_id=request["job_id"],
        request_id=request["request_id"],
        participant_node_ids=expected_nodes,
        bundle_path=output_path,
    )
