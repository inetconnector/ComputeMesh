"""Tests for owner-authenticated public promo onboarding routes."""
import base64
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.billing.owner_accounts import PROMO_DEVICE, PROMO_GPU, OwnerAccountStore
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


class FakePromoControlPlane:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self.private_key = private_key
        self.challenge_requests: list[dict] = []
        self.verify_requests: list[dict] = []
        self.malformed_challenge = False

    def issue_challenge(self, body: dict) -> dict:
        self.challenge_requests.append(body)
        if self.malformed_challenge:
            return {"challenge_id": "bad"}
        return {
            "challenge_id": "promo_ch_test",
            "claim_class": body["claim_class"],
            "owner_id": body["owner_id"],
            "node_id": body["node_id"],
            "key_id": body["key_id"],
            "hardware_claim_id": "cmhw_v1_testhardware",
            "evidence_digest": "sha256:" + "ab" * 32,
            "nonce": "nonce-test",
            "issued_at": 1_000,
            "expires_at": 1_120,
        }

    def verify_and_issue(self, body: dict) -> dict:
        self.verify_requests.append(body)
        proof = body["proof"]
        issued = int(time.time())
        policy = "onboarding-test-v1"
        claim_id = promo_claim_id(
            owner_id=proof["owner_id"],
            claim_class=proof["claim_class"],
            hardware_claim_id=proof["hardware_claim_id"],
            policy_version=policy,
        )
        unsigned = {
            "kind": PROMO_DECISION_KIND,
            "decision_id": "promo_dec_gateway_test",
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
                "key_id": "promo-test-key",
                "value": _b64u(
                    self.private_key.sign(canonical_unsigned_envelope(unsigned))
                ),
            },
        }


class TestOwnerPromoRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.owner_store = OwnerAccountStore(root / "owners.sqlite3")
        self.ledger = OwnerCreditLedger(storage_path=root / "ledger.jsonl")
        self.teaser = TeaserQuotaManager(max_requests=1, max_tokens=10)
        self.token = "cm_owner_alice_123"
        self.auth = GatewayAuthManager(
            ledger=self.ledger,
            teaser_manager=self.teaser,
            api_keys={self.token: "alice"},
            owner_account_store=self.owner_store,
        )
        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
        self.control_plane = FakePromoControlPlane(self.private_key)
        self.routes = UnifiedOwnerPromoRoutes(
            owner_store=self.owner_store,
            ledger=self.ledger,
            auth_manager=self.auth,
            control_plane=self.control_plane,  # type: ignore[arg-type]
            applier=SignedPromoGrantApplier(
                owner_store=self.owner_store,
                ledger=self.ledger,
                verifier=PromoDecisionVerifier({"promo-test-key": public_key}),
            ),
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _challenge_body(claim_class: str = PROMO_DEVICE, node_id: str = "device-1") -> dict:
        return {
            "claim_class": claim_class,
            "node_id": node_id,
            "key_id": "ed25519:test-key",
            "hardware_evidence": {
                "board_uuid": "board-1",
                "cpu_fingerprint": "cpu-1",
            },
        }

    @staticmethod
    def _proof(
        *,
        claim_class: str,
        owner_id: str = "alice",
        node_id: str = "device-1",
        hardware_claim_id: str = "cmhw_v1_testhardware",
    ) -> dict:
        return {
            "challenge_id": "promo_ch_test",
            "claim_class": claim_class,
            "owner_id": owner_id,
            "node_id": node_id,
            "key_id": "ed25519:test-key",
            "hardware_claim_id": hardware_claim_id,
            "evidence_digest": "sha256:" + "ab" * 32,
            "nonce": "nonce-test",
            "assurance_tier": "MULTI_SIGNAL_VERIFIED",
            "public_key_b64u": _b64u(b"p" * 32),
            "signature_b64u": _b64u(b"s" * 64),
            "accelerator_id": "gpu-1" if claim_class == PROMO_GPU else "",
            "runtime_backend": "cuda" if claim_class == PROMO_GPU else "",
            "runtime_build": "llama.cpp-test" if claim_class == PROMO_GPU else "",
            "work_digest": "sha256:work" if claim_class == PROMO_GPU else "",
            "elapsed_ms": 12.0 if claim_class == PROMO_GPU else 0.0,
        }

    def test_authenticated_owner_is_injected_into_private_challenge(self) -> None:
        payload, error, status = self.routes.handle_challenge(
            self.headers,
            self._challenge_body(),
        )
        self.assertIsNone(error)
        self.assertEqual(int(status), 200)
        assert payload is not None
        self.assertEqual(payload["owner_id"], "alice")
        self.assertEqual(self.control_plane.challenge_requests[0]["owner_id"], "alice")

        bad = {**self._challenge_body(), "owner_id": "bob"}
        payload, error, status = self.routes.handle_challenge(self.headers, bad)
        self.assertIsNone(payload)
        self.assertEqual(int(status), 400)
        self.assertIn("Invalid", error or "")

    def test_foreign_gpu_node_is_rejected_before_private_control_plane(self) -> None:
        self.owner_store.ensure_owner("bob")
        self.owner_store.bind_provider_node("bob", "rig-bob")
        payload, error, status = self.routes.handle_challenge(
            self.headers,
            self._challenge_body(PROMO_GPU, "rig-bob"),
        )
        self.assertIsNone(payload)
        self.assertEqual(int(status), 403)
        self.assertIn("not owned", error or "")
        self.assertEqual(self.control_plane.challenge_requests, [])

    def test_verify_uses_lifetime_claim_sum_not_remaining_wallet(self) -> None:
        self.owner_store.ensure_owner("alice")
        self.owner_store.record_promo_claim(
            claim_id="existing-device-claim",
            owner_id="alice",
            claim_class=PROMO_DEVICE,
            hardware_claim_id="cmhw_v1_old-device",
            amount_micro_units=25_000_000,
            policy_version="old-policy",
        )
        # Deliberately no promo money in the ledger: this models a fully spent grant.
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 0)
        self.owner_store.bind_provider_node("alice", "rig-alice")

        payload, error, status = self.routes.handle_verify(
            self.headers,
            {
                "proof": self._proof(
                    claim_class=PROMO_GPU,
                    node_id="rig-alice",
                    hardware_claim_id="cmhw_v1_new-gpu-device",
                )
            },
        )
        self.assertIsNone(error)
        self.assertEqual(int(status), 200)
        assert payload is not None
        eligibility = self.control_plane.verify_requests[0]["eligibility"]
        self.assertEqual(eligibility["current_owner_promo_micro_units"], 25_000_000)
        self.assertEqual(eligibility["already_claimed_classes"], [PROMO_DEVICE])
        self.assertEqual(payload["promo_balance_micro_units"], 25_000_000)

    def test_existing_claim_repairs_missing_ledger_without_new_private_challenge(self) -> None:
        self.owner_store.ensure_owner("alice")
        self.owner_store.record_promo_claim(
            claim_id="durable-device-claim",
            owner_id="alice",
            claim_class=PROMO_DEVICE,
            hardware_claim_id="cmhw_v1_recovery-device",
            amount_micro_units=25_000_000,
            policy_version="onboarding-test-v1",
        )
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 0)

        payload, error, status = self.routes.handle_challenge(
            self.headers,
            self._challenge_body(),
        )
        self.assertIsNone(error)
        self.assertEqual(int(status), 200)
        assert payload is not None
        self.assertEqual(payload["status"], "already_claimed")
        self.assertEqual(payload["ledger_status"], "credited_recovery")
        self.assertEqual(payload["promo_balance_micro_units"], 25_000_000)
        self.assertEqual(self.control_plane.challenge_requests, [])

        payload, error, status = self.routes.handle_challenge(
            self.headers,
            self._challenge_body(),
        )
        assert payload is not None
        self.assertEqual(payload["ledger_status"], "already_credited")
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 25_000_000)

    def test_malformed_private_challenge_response_fails_closed(self) -> None:
        self.control_plane.malformed_challenge = True
        payload, error, status = self.routes.handle_challenge(
            self.headers,
            self._challenge_body(),
        )
        self.assertIsNone(payload)
        self.assertEqual(int(status), 502)
        self.assertIn("Invalid promo service", error or "")

    def test_proof_owner_must_match_authenticated_owner(self) -> None:
        payload, error, status = self.routes.handle_verify(
            self.headers,
            {"proof": self._proof(claim_class=PROMO_DEVICE, owner_id="bob")},
        )
        self.assertIsNone(payload)
        self.assertEqual(int(status), 403)
        self.assertIn("authenticated owner", error or "")
        self.assertEqual(self.control_plane.verify_requests, [])


if __name__ == "__main__":
    unittest.main()
