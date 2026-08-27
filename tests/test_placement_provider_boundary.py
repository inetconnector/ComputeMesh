from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.orchestrator.placement_provider import (
    PlacementProviderError,
    _canonical_unsigned_envelope,
    _external_plan,
    _verify_envelope,
)


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _envelope() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "decision_type": "placement",
        "decision_id": "decision-1",
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
        "payload": {
            "model": {
                "model_id": "model-1",
                "artifact_digest": "sha256:" + "a" * 64,
                "artifact_size_bytes": 1024,
                "layer_count": 4,
            },
            "execution": {
                "coordinator": {"node_id": "node-a", "kind": "gpu", "name": "GPU A"},
                "worker": {"node_id": "node-b"},
                "layer_ranges": [
                    {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 2},
                    {"node_id": "node-b", "start_layer": 2, "end_layer_exclusive": 4},
                ],
                "tensor_split": [2.0, 2.0],
            },
        },
    }


def test_signed_external_plan_round_trip() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    envelope = _envelope()
    envelope["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "cp-test",
        "value": _b64u(private_key.sign(_canonical_unsigned_envelope(envelope))),
    }
    _verify_envelope(envelope, verification_key_b64u=_b64u(public_raw), expected_key_id="cp-test")
    plan = _external_plan(envelope)
    assert plan.coordinator_node_id == "node-a"
    assert plan.worker_node_id == "node-b"
    assert plan.layer_ranges == (("node-a", 0, 2), ("node-b", 2, 4))


def test_tampered_placement_is_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    envelope = _envelope()
    envelope["signature"] = {
        "algorithm": "Ed25519",
        "key_id": "cp-test",
        "value": _b64u(private_key.sign(_canonical_unsigned_envelope(envelope))),
    }
    envelope["payload"]["execution"]["tensor_split"] = [3.0, 1.0]
    with pytest.raises(PlacementProviderError, match="signature verification failed"):
        _verify_envelope(envelope, verification_key_b64u=_b64u(public_raw), expected_key_id="cp-test")


def test_invalid_non_contiguous_plan_is_rejected() -> None:
    envelope = _envelope()
    envelope["payload"]["execution"]["layer_ranges"][1]["start_layer"] = 3
    with pytest.raises(PlacementProviderError, match="invalid execution data"):
        _external_plan(envelope)
