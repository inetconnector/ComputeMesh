"""Public boundary between ComputeMesh execution and private placement policy."""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from services.scheduler.placement import build_placement_decision


class PlacementProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlacementPlan:
    """Minimal execution data allowed to cross the private-policy boundary."""

    decision_id: str
    model_id: str
    artifact_digest: str
    artifact_size_bytes: int
    layer_count: int
    coordinator_node_id: str
    coordinator_kind: str
    coordinator_name: str
    worker_node_id: str
    layer_ranges: tuple[tuple[str, int, int], ...]
    tensor_split: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.decision_id or not self.model_id or not self.artifact_digest:
            raise ValueError("placement identifiers must be non-empty")
        if self.artifact_size_bytes < 1 or self.layer_count < 2:
            raise ValueError("placement model metadata is invalid")
        if not self.coordinator_node_id or not self.worker_node_id or self.coordinator_node_id == self.worker_node_id:
            raise ValueError("placement requires distinct coordinator and worker")
        if len(self.layer_ranges) != 2 or len(self.tensor_split) != 2:
            raise ValueError("current live executor requires exactly two placement stages")
        if any(value <= 0 for value in self.tensor_split):
            raise ValueError("tensor split entries must be positive")
        ordered = sorted(self.layer_ranges, key=lambda item: item[1])
        if ordered[0][1] != 0 or ordered[0][2] != ordered[1][1] or ordered[-1][2] != self.layer_count:
            raise ValueError("placement layer ranges must be contiguous and cover the model")
        if {item[0] for item in self.layer_ranges} != {self.coordinator_node_id, self.worker_node_id}:
            raise ValueError("placement layer ranges do not match selected nodes")


class PlacementProvider(Protocol):
    def decide(self, **inputs: Any) -> PlacementPlan: ...


def _reference_plan(decision: dict[str, Any]) -> PlacementPlan:
    recommendation = decision["recommendation"]
    if recommendation["production_scheduling"] is not False or recommendation["mode"] != "shared_experiment":
        raise PlacementProviderError("reference scheduler did not return a shared experimental placement")
    if not all(bool(item["passed"]) for item in decision["hard_constraints"]):
        raise PlacementProviderError("reference placement hard constraints are not all satisfied")
    shared = [c for c in decision["candidates"] if c["mode"] == "shared_contiguous_layers" and c["feasible"]]
    if len(shared) != 1:
        raise PlacementProviderError("reference scheduler did not return one feasible shared placement")
    candidate = shared[0]
    model = decision["model"]
    coordinator = decision["nodes"]["coordinator"]
    worker = decision["nodes"]["worker"]
    return PlacementPlan(
        decision_id=str(decision["decision_id"]),
        model_id=str(model["model_id"]),
        artifact_digest=str(model["artifact_digest"]),
        artifact_size_bytes=int(model["artifact_size_bytes"]),
        layer_count=int(model["layer_count"]),
        coordinator_node_id=str(coordinator["node_id"]),
        coordinator_kind=str(coordinator["kind"]),
        coordinator_name=str(coordinator["name"]),
        worker_node_id=str(worker["node_id"]),
        layer_ranges=tuple((str(item["node_id"]), int(item["start_layer"]), int(item["end_layer_exclusive"])) for item in candidate["layer_ranges"]),
        tensor_split=tuple(float(value) for value in candidate["tensor_split"]),
    )


@dataclass(frozen=True)
class ReferencePlacementProvider:
    """Disclosed M1 planner for research/reproducibility, never production policy."""

    def decide(self, **inputs: Any) -> PlacementPlan:
        return _reference_plan(build_placement_decision(**inputs))


def _b64u_decode(value: str, expected_bytes: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise PlacementProviderError("placement signature/public key encoding is empty")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise PlacementProviderError("placement signature/public key is not base64url")
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise PlacementProviderError("placement signature/public key is malformed") from exc
    if len(raw) != expected_bytes:
        raise PlacementProviderError("placement signature/public key has unexpected length")
    return raw


def _canonical_unsigned_envelope(value: dict[str, Any]) -> bytes:
    unsigned = dict(value)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_envelope(value: dict[str, Any], *, verification_key_b64u: str, expected_key_id: str) -> None:
    signature = value.get("signature")
    if not isinstance(signature, dict):
        raise PlacementProviderError("private placement response is unsigned")
    if signature.get("algorithm") != "Ed25519" or signature.get("key_id") != expected_key_id:
        raise PlacementProviderError("private placement response uses an unexpected signing key")
    try:
        Ed25519PublicKey.from_public_bytes(_b64u_decode(verification_key_b64u, 32)).verify(
            _b64u_decode(signature.get("value"), 64), _canonical_unsigned_envelope(value)
        )
    except (InvalidSignature, ValueError) as exc:
        raise PlacementProviderError("private placement signature verification failed") from exc
    try:
        issued = datetime.fromisoformat(str(value["issued_at"]).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(str(value["expires_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise PlacementProviderError("private placement timestamps are invalid") from exc
    if issued.tzinfo is None or expires.tzinfo is None:
        raise PlacementProviderError("private placement timestamps must be timezone-aware")
    now = datetime.now(UTC)
    if expires.astimezone(UTC) <= now:
        raise PlacementProviderError("private placement decision has expired")
    if issued.astimezone(UTC) > now + timedelta(seconds=30):
        raise PlacementProviderError("private placement decision exceeds allowed clock skew")


def _external_plan(value: dict[str, Any]) -> PlacementPlan:
    if value.get("schema_version") != 2 or value.get("decision_type") != "execution_plan":
        raise PlacementProviderError("private placement response has an unsupported envelope")
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise PlacementProviderError("private placement response lacks payload")
    model, execution = payload.get("model"), payload.get("execution")
    if not isinstance(model, dict) or not isinstance(execution, dict) or execution.get("executor_version") != 1:
        raise PlacementProviderError("private placement response lacks supported execution data")
    coordinator = execution.get("coordinator")
    stages = execution.get("stages")
    if not isinstance(coordinator, dict) or not isinstance(stages, list) or len(stages) != 2:
        raise PlacementProviderError("current public executor requires exactly two signed stages")
    try:
        ranges = tuple((str(item["node_id"]), int(item["start_layer"]), int(item["end_layer_exclusive"])) for item in stages)
        split = tuple(float(item["tensor_weight"]) for item in stages)
        coordinator_id = str(coordinator["node_id"])
        worker_id = next(item[0] for item in ranges if item[0] != coordinator_id)
        return PlacementPlan(
            decision_id=str(value["decision_id"]),
            model_id=str(model["model_id"]),
            artifact_digest=str(model["artifact_digest"]),
            artifact_size_bytes=int(model["artifact_size_bytes"]),
            layer_count=int(model["layer_count"]),
            coordinator_node_id=coordinator_id,
            coordinator_kind=str(coordinator["kind"]),
            coordinator_name=str(coordinator["name"]),
            worker_node_id=worker_id,
            layer_ranges=ranges,
            tensor_split=split,
        )
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise PlacementProviderError("private placement payload contains invalid execution data") from exc


@dataclass(frozen=True)
class RemotePlacementProvider:
    """Fail-closed HTTPS client for the private global production scheduler."""

    endpoint: str
    bearer_token: str
    verification_key_b64u: str
    expected_key_id: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise ValueError("production placement endpoint must use HTTPS")
        if not self.bearer_token:
            raise ValueError("placement bearer token must be non-empty")
        _b64u_decode(self.verification_key_b64u, 32)
        if not self.expected_key_id:
            raise ValueError("placement signing key id must be non-empty")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be within (0,60]")

    def decide(self, **inputs: Any) -> PlacementPlan:
        allowed = {"model_manifest", "candidates", "network_edges", "constraints"}
        if set(inputs) != allowed:
            raise PlacementProviderError("production placement requires one global candidate-pool request")
        req = urlrequest.Request(
            self.endpoint,
            data=json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self.bearer_token}", "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read(512 * 1024 + 1)
        except (urlerror.URLError, TimeoutError) as exc:
            raise PlacementProviderError("private placement service is unavailable") from exc
        if len(raw) > 512 * 1024:
            raise PlacementProviderError("private placement response exceeded 512 KiB")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PlacementProviderError("private placement service returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise PlacementProviderError("private placement response must be an object")
        _verify_envelope(value, verification_key_b64u=self.verification_key_b64u, expected_key_id=self.expected_key_id)
        return _external_plan(value)
