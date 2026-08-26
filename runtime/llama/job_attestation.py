#!/usr/bin/env python3
"""Create and sign job-bound execution-attestation requests for shared llama.cpp runs.

The coordinator emits a request containing only public execution claims. Each
participant signs that request locally with its own enrolled Ed25519 private key;
private keys never need to leave the node that owns them.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator, FormatChecker

from protocol.node_identity import key_id_from_public_key
from services.gateway.execution_attestation import AttestationClaims, create_execution_attestation

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_SCHEMA = ROOT / "runtime" / "llama" / "shared_run_evidence.schema.json"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_KEY_BYTES = 64 * 1024


class JobAttestationError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not (0 < path.stat().st_size <= MAX_JSON_BYTES):
        raise JobAttestationError("input must be a bounded regular JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JobAttestationError("input must contain UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise JobAttestationError("input JSON root must be an object")
    return value


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_attestation_request(*, job_id: str, evidence_path: Path) -> dict[str, Any]:
    if not isinstance(job_id, str) or not (1 <= len(job_id) <= 256):
        raise JobAttestationError("job_id must be 1..256 characters")
    evidence = _load_json(evidence_path)
    schema = _load_json(EVIDENCE_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(evidence),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "$"
        raise JobAttestationError(f"shared-run evidence invalid at {where}: {first.message}")

    nodes = [str(item["node_id"]) for item in evidence["planner_split"]["layer_ranges"]]
    if len(nodes) < 2 or len(set(nodes)) != len(nodes):
        raise JobAttestationError("shared-run evidence must contain distinct participants")
    evidence_raw = evidence_path.read_bytes()
    request_doc = {
        "schema_version": 1,
        "job_id": job_id,
        "placement_decision_id": evidence["placement_decision_id"],
        "model_sha256": evidence["model"]["sha256"],
        "runtime_sha256": _canonical_sha256(evidence["runtime"]),
        "evidence_sha256": hashlib.sha256(evidence_raw).hexdigest(),
        "output_sha256": evidence["correctness"]["shared_output_sha256"],
        "expected_nodes": nodes,
    }
    request_doc["request_id"] = "execution-attestation-request-" + _canonical_sha256(request_doc)[:16]
    return request_doc


def write_attestation_request(*, job_id: str, evidence_path: Path, output_path: Path) -> Path:
    if output_path.exists():
        raise JobAttestationError("attestation request output already exists")
    request_doc = build_attestation_request(job_id=job_id, evidence_path=evidence_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(request_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    if path.is_symlink() or not path.is_file() or not (0 < path.stat().st_size <= MAX_KEY_BYTES):
        raise JobAttestationError("private key must be a bounded regular file")
    raw = path.read_bytes()
    try:
        if len(raw) == 32:
            return Ed25519PrivateKey.from_private_bytes(raw)
        if raw.startswith(b"-----BEGIN"):
            key = serialization.load_pem_private_key(raw, password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise JobAttestationError("private key is not Ed25519")
            return key
        stripped = raw.strip()
        try:
            decoded = base64.b64decode(stripped, validate=True)
        except Exception:
            decoded = stripped
        if len(decoded) != 32:
            raise JobAttestationError("raw/base64 Ed25519 private key must contain 32 bytes")
        return Ed25519PrivateKey.from_private_bytes(decoded)
    except JobAttestationError:
        raise
    except Exception as exc:
        raise JobAttestationError("private key could not be loaded") from exc


def sign_attestation_request(
    *,
    request_path: Path,
    node_id: str,
    private_key_path: Path,
    now: datetime | None = None,
    ttl: timedelta = timedelta(minutes=2),
) -> dict[str, Any]:
    request_doc = _load_json(request_path)
    required = {
        "schema_version", "request_id", "job_id", "placement_decision_id", "model_sha256",
        "runtime_sha256", "evidence_sha256", "output_sha256", "expected_nodes",
    }
    if set(request_doc) != required or request_doc["schema_version"] != 1:
        raise JobAttestationError("invalid attestation request envelope")
    canonical_without_id = {k: v for k, v in request_doc.items() if k != "request_id"}
    expected_request_id = "execution-attestation-request-" + _canonical_sha256(canonical_without_id)[:16]
    if request_doc["request_id"] != expected_request_id:
        raise JobAttestationError("attestation request id does not match its claims")
    expected_nodes = request_doc["expected_nodes"]
    if not isinstance(expected_nodes, list) or node_id not in expected_nodes:
        raise JobAttestationError("node is not an expected participant for this request")
    if ttl <= timedelta(0) or ttl > timedelta(minutes=5):
        raise JobAttestationError("attestation ttl must be positive and <= 5 minutes")

    private_key = _load_private_key(private_key_path)
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_id = key_id_from_public_key(public_raw)
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires = issued + ttl
    claims = AttestationClaims(
        node_id=node_id,
        key_id=key_id,
        job_id=request_doc["job_id"],
        placement_decision_id=request_doc["placement_decision_id"],
        model_sha256=request_doc["model_sha256"],
        runtime_sha256=request_doc["runtime_sha256"],
        evidence_sha256=request_doc["evidence_sha256"],
        output_sha256=request_doc["output_sha256"],
        issued_at=int(issued.timestamp()),
        expires_at=int(expires.timestamp()),
    )
    return create_execution_attestation(private_key=private_key, claims=claims)


def write_node_attestation(
    *, request_path: Path, node_id: str, private_key_path: Path, output_path: Path
) -> Path:
    if output_path.exists():
        raise JobAttestationError("node attestation output already exists")
    doc = sign_attestation_request(
        request_path=request_path,
        node_id=node_id,
        private_key_path=private_key_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def assemble_attestation_bundle(*, request_path: Path, attestation_paths: list[Path], output_path: Path) -> Path:
    request_doc = _load_json(request_path)
    expected_nodes = request_doc.get("expected_nodes")
    if not isinstance(expected_nodes, list):
        raise JobAttestationError("attestation request expected_nodes is invalid")
    attestations = [_load_json(path) for path in attestation_paths]
    nodes = [item.get("node_id") for item in attestations]
    if len(attestations) != len(expected_nodes) or set(nodes) != set(expected_nodes) or len(set(nodes)) != len(nodes):
        raise JobAttestationError("attestation bundle must contain exactly one attestation per expected node")
    if output_path.exists():
        raise JobAttestationError("attestation bundle output already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"schema_version": 1, "attestations": attestations}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh job-bound execution attestation tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    request_parser = sub.add_parser("request")
    request_parser.add_argument("--job-id", required=True)
    request_parser.add_argument("--evidence", type=Path, required=True)
    request_parser.add_argument("--output", type=Path, required=True)

    sign_parser = sub.add_parser("sign")
    sign_parser.add_argument("--request", type=Path, required=True)
    sign_parser.add_argument("--node-id", required=True)
    sign_parser.add_argument("--private-key", type=Path, required=True)
    sign_parser.add_argument("--output", type=Path, required=True)

    bundle_parser = sub.add_parser("bundle")
    bundle_parser.add_argument("--request", type=Path, required=True)
    bundle_parser.add_argument("--attestation", type=Path, action="append", required=True)
    bundle_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "request":
            result = write_attestation_request(job_id=args.job_id, evidence_path=args.evidence, output_path=args.output)
        elif args.command == "sign":
            result = write_node_attestation(
                request_path=args.request,
                node_id=args.node_id,
                private_key_path=args.private_key,
                output_path=args.output,
            )
        else:
            result = assemble_attestation_bundle(
                request_path=args.request,
                attestation_paths=args.attestation,
                output_path=args.output,
            )
    except Exception as exc:
        print(f"job attestation failed: {type(exc).__name__}: {str(exc)[:1024]}")
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
