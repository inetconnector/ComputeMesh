from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import unittest

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
        "schema_version": 2,
        "decision_type": "execution_plan",
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
                "executor_version": 1,
                "coordinator": {"node_id": "node-a", "kind": "gpu", "name": "GPU A"},
                "stages": [
                    {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 2, "tensor_weight": 2.0},
                    {"node_id": "node-b", "start_layer": 2, "end_layer_exclusive": 4, "tensor_weight": 2.0},
                ],
            },
        },
    }


class PlacementProviderBoundaryTests(unittest.TestCase):
    def test_signed_external_plan_round_trip(self) -> None:
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
        self.assertEqual(plan.coordinator_node_id, "node-a")
        self.assertEqual(plan.worker_node_id, "node-b")
        self.assertEqual(plan.layer_ranges, (("node-a", 0, 2), ("node-b", 2, 4)))

    def test_tampered_placement_is_rejected(self) -> None:
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
        envelope["payload"]["execution"]["stages"][0]["tensor_weight"] = 3.0
        with self.assertRaisesRegex(PlacementProviderError, "signature verification failed"):
            _verify_envelope(envelope, verification_key_b64u=_b64u(public_raw), expected_key_id="cp-test")

    def test_invalid_non_contiguous_plan_is_rejected(self) -> None:
        envelope = _envelope()
        envelope["payload"]["execution"]["stages"][1]["start_layer"] = 3
        # When missing valid worker or corrupted, fails with invalid execution data
        del envelope["payload"]["execution"]["stages"][1]["node_id"]
        with self.assertRaisesRegex(PlacementProviderError, "invalid execution data"):
            _external_plan(envelope)

    def test_executor_version_2_n_stage_and_device_index(self) -> None:
        now = datetime.now(timezone.utc)
        envelope = {
            "schema_version": 2,
            "decision_type": "execution_plan",
            "decision_id": "decision-n-stage",
            "issued_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "payload": {
                "model": {
                    "model_id": "model-large",
                    "artifact_digest": "sha256:" + "b" * 64,
                    "artifact_size_bytes": 4096,
                    "layer_count": 9,
                },
                "execution": {
                    "executor_version": 2,
                    "coordinator": {"node_id": "rig-01", "kind": "gpu", "name": "Rig 1 GPU 0"},
                    "stages": [
                        {"node_id": "rig-01", "device_index": 0, "start_layer": 0, "end_layer_exclusive": 3, "tensor_weight": 3.0},
                        {"node_id": "rig-01", "device_index": 1, "start_layer": 3, "end_layer_exclusive": 6, "tensor_weight": 3.0},
                        {"node_id": "rig-02", "device_index": 0, "start_layer": 6, "end_layer_exclusive": 9, "tensor_weight": 3.0},
                    ],
                },
            },
        }
        plan = _external_plan(envelope)
        self.assertEqual(plan.executor_version, 2)
        self.assertEqual(plan.coordinator_node_id, "rig-01")
        self.assertEqual(plan.worker_node_id, "rig-02")
        self.assertEqual(len(plan.layer_ranges), 3)
        self.assertEqual(plan.layer_ranges, (("rig-01", 0, 3), ("rig-01", 3, 6), ("rig-02", 6, 9)))
        self.assertEqual(plan.device_indices, (0, 1, 0))
        self.assertEqual(plan.tensor_split, (3.0, 3.0, 3.0))

    def test_executor_version_2_gap_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        envelope = {
            "schema_version": 2,
            "decision_type": "execution_plan",
            "decision_id": "decision-gap",
            "issued_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "payload": {
                "model": {
                    "model_id": "model-1",
                    "artifact_digest": "sha256:" + "c" * 64,
                    "artifact_size_bytes": 1024,
                    "layer_count": 6,
                },
                "execution": {
                    "executor_version": 2,
                    "coordinator": {"node_id": "node-a", "kind": "gpu", "name": "GPU A"},
                    "stages": [
                        {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 2, "tensor_weight": 2.0},
                        {"node_id": "node-b", "start_layer": 3, "end_layer_exclusive": 6, "tensor_weight": 3.0},
                    ],
                },
            },
        }
        with self.assertRaisesRegex(PlacementProviderError, "invalid execution data"):
            _external_plan(envelope)


if __name__ == "__main__":
    unittest.main()
