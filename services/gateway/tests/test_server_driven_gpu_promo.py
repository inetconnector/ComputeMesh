"""Tests for the server-driven GPU onboarding chain."""
from __future__ import annotations

import base64
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.billing.owner_accounts import PROMO_GPU, OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.signed_promo_grants import (
    PROMO_DECISION_KIND,
    PromoDecisionVerifier,
    SignedPromoGrantApplier,
    canonical_unsigned_envelope,
    promo_claim_id,
)
from services.gateway.auth import GatewayAuthManager
from services.gateway.owner_promo_routes import UnifiedOwnerPromoRoutes
from services.gateway.teaser import TeaserQuotaManager


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class _PrivatePromo:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self.private_key = private_key
        self.challenge_requests: list[dict] = []
        self.gpu_work_requests: list[dict] = []
        self.verify_requests: list[dict] = []

    def issue_challenge(self, body: dict) -> dict:
        self.challenge_requests.append(body)
        return {
            "challenge_id": "promo_ch_gpu_server",
            "claim_class": body["claim_class"],
            "owner_id": body["owner_id"],
            "node_id": body["node_id"],
            "key_id": body["key_id"],
            "hardware_claim_id": "cmhw_v1_gpu-server",
            "evidence_digest": "sha256:" + "1" * 64,
            "nonce": "n" * 32,
            "issued_at": 1_000,
            "expires_at": 1_120,
        }

    def gpu_work(self, body: dict) -> dict:
        self.gpu_work_requests.append(body)
        return {
            "schema_version": 1,
            "challenge_id": body["challenge_id"],
            "claim_class": PROMO_GPU,
            "owner_id": body["owner_id"],
            "node_id": body["node_id"],
            "key_id": body["key_id"],
            "hardware_claim_id": "cmhw_v1_gpu-server",
            "evidence_digest": "sha256:" + "1" * 64,
            "nonce": "n" * 32,
            "prompt": "ComputeMesh private GPU work vector",
            "seed": 17,
            "n_predict": 16,
            "model_sha256": "2" * 64,
            "expected_llama_build_number": 123,
            "expected_llama_build_commit": "abcdef1",
            "timeout_ms": 30_000,
        }

    def verify_and_issue(self, body: dict) -> dict:
        self.verify_requests.append(body)
        proof = body["proof"]
        issued = int(time.time())
        policy = "onboarding-test-server-gpu-v1"
        claim_id = promo_claim_id(
            owner_id=proof["owner_id"],
            claim_class=proof["claim_class"],
            hardware_claim_id=proof["hardware_claim_id"],
            policy_version=policy,
        )
        unsigned = {
            "kind": PROMO_DECISION_KIND,
            "decision_id": "promo_dec_server_gpu_test",
            "issued_at": issued,
            "expires_at": issued + 120,
            "owner_id": proof["owner_id"],
            "claim_id": claim_id,
            "claim_class": proof["claim_class"],
            "hardware_claim_id": proof["hardware_claim_id"],
            "assurance_tier": proof["assurance_tier"],
            "node_id": proof["node_id"],
            "amount_micro_units": 25_000_000,
            "policy_version": policy,
            "evidence_digest": proof["evidence_digest"],
        }
        return {
            **unsigned,
            "signature": {
                "algorithm": "Ed25519",
                "key_id": "promo-server-test-key",
                "value": _b64u(self.private_key.sign(canonical_unsigned_envelope(unsigned))),
            },
        }


class _Dispatcher:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def dispatch(self, *, node_id: str, challenge: dict) -> dict:
        self.calls.append({"node_id": node_id, "challenge": challenge})
        return {
            "proof": {
                "challenge_id": challenge["challenge_id"],
                "claim_class": challenge["claim_class"],
                "owner_id": challenge["owner_id"],
                "node_id": challenge["node_id"],
                "key_id": challenge["key_id"],
                "hardware_claim_id": challenge["hardware_claim_id"],
                "evidence_digest": challenge["evidence_digest"],
                "nonce": challenge["nonce"],
                "assurance_tier": "MULTI_SIGNAL_VERIFIED",
                "public_key_b64u": _b64u(b"p" * 32),
                "signature_b64u": _b64u(b"s" * 64),
                "accelerator_id": "GPU-uuid-1",
                "runtime_backend": "cuda",
                "runtime_build": "llama.cpp:123:abcdef1;model_sha256:" + "2" * 64 + ";device:CUDA0",
                "work_digest": "sha256:" + "3" * 64,
                "elapsed_ms": 125.0,
            },
            "gpu_observation": {
                "server_roundtrip_ms": 500.0,
                "session_id": "session-rig-alice",
                "session_revision": 7,
            },
        }


class TestServerDrivenGpuPromo(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.owner_store = OwnerAccountStore(root / "owners.sqlite3")
        self.ledger = OwnerCreditLedger(storage_path=root / "ledger.jsonl")
        self.token = "cm_owner_alice_server_gpu"
        auth = GatewayAuthManager(
            ledger=self.ledger,
            teaser_manager=TeaserQuotaManager(max_requests=1, max_tokens=10),
            api_keys={self.token: "alice"},
            owner_account_store=self.owner_store,
        )
        self.decision_private = Ed25519PrivateKey.generate()
        public_key = self.decision_private.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
        self.private = _PrivatePromo(self.decision_private)
        self.dispatcher = _Dispatcher()
        self.routes = UnifiedOwnerPromoRoutes(
            owner_store=self.owner_store,
            ledger=self.ledger,
            auth_manager=auth,
            control_plane=self.private,  # type: ignore[arg-type]
            applier=SignedPromoGrantApplier(
                owner_store=self.owner_store,
                ledger=self.ledger,
                verifier=PromoDecisionVerifier({"promo-server-test-key": public_key}),
            ),
            gpu_dispatch=self.dispatcher,  # type: ignore[arg-type]
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.owner_store.ensure_owner("alice")
        self.owner_store.bind_provider_node("alice", "rig-alice")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _body(node_id: str = "rig-alice") -> dict:
        return {
            "node_id": node_id,
            "key_id": "ed25519:node-key-a",
            "hardware_evidence": {
                "board_uuid": "board-a",
                "cpu_fingerprint": "cpu-a",
                "gpu_ids": ["GPU-uuid-1"],
            },
        }

    def test_server_driven_gpu_flow_uses_private_work_and_server_observation(self) -> None:
        payload, error, status = self.routes.handle_gpu_onboard(self.headers, self._body())
        self.assertIsNone(error)
        self.assertEqual(int(status), 200)
        assert payload is not None
        self.assertEqual(payload["status"], "credited")
        self.assertEqual(payload["claim_class"], PROMO_GPU)
        self.assertEqual(payload["promo_balance_micro_units"], 25_000_000)

        self.assertEqual(len(self.private.challenge_requests), 1)
        self.assertEqual(len(self.private.gpu_work_requests), 1)
        self.assertEqual(len(self.dispatcher.calls), 1)
        self.assertEqual(len(self.private.verify_requests), 1)
        verify = self.private.verify_requests[0]
        self.assertEqual(
            verify["gpu_observation"],
            {
                "server_roundtrip_ms": 500.0,
                "session_id": "session-rig-alice",
                "session_revision": 7,
            },
        )
        self.assertEqual(verify["eligibility"]["provider_node_owner_id"], "alice")
        self.assertEqual(verify["eligibility"]["current_owner_promo_micro_units"], 0)
        self.assertEqual(
            self.dispatcher.calls[0]["challenge"]["prompt"],
            "ComputeMesh private GPU work vector",
        )

    def test_foreign_node_is_rejected_before_private_or_dispatch_calls(self) -> None:
        self.owner_store.ensure_owner("bob")
        self.owner_store.bind_provider_node("bob", "rig-bob")
        payload, error, status = self.routes.handle_gpu_onboard(
            self.headers,
            self._body("rig-bob"),
        )
        self.assertIsNone(payload)
        self.assertEqual(int(status), 403)
        self.assertIn("not owned", error or "")
        self.assertEqual(self.private.challenge_requests, [])
        self.assertEqual(self.dispatcher.calls, [])

    def test_server_driven_mode_rejects_client_supplied_gpu_proof(self) -> None:
        proof = self.dispatcher.dispatch(
            node_id="rig-alice",
            challenge=self.private.gpu_work(
                {
                    "challenge_id": "promo_ch_gpu_server",
                    "owner_id": "alice",
                    "node_id": "rig-alice",
                    "key_id": "ed25519:node-key-a",
                }
            ),
        )["proof"]
        self.private.gpu_work_requests.clear()
        self.dispatcher.calls.clear()
        payload, error, status = self.routes.handle_verify(
            self.headers,
            {"proof": proof},
        )
        self.assertIsNone(payload)
        self.assertEqual(int(status), 400)
        self.assertIn("disabled", error or "")
        self.assertEqual(self.private.verify_requests, [])

    def test_server_driven_mode_rejects_legacy_gpu_challenge_endpoint(self) -> None:
        payload, error, status = self.routes.handle_challenge(
            self.headers,
            {"claim_class": PROMO_GPU, **self._body()},
        )
        self.assertIsNone(payload)
        self.assertEqual(int(status), 400)
        self.assertIn("server-driven", error or "")
        self.assertEqual(self.private.challenge_requests, [])


if __name__ == "__main__":
    unittest.main()
