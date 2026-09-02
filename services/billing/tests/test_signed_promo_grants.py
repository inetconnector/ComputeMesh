"""Tests for signed private-control-plane promo grant consumption."""
from dataclasses import replace
import base64
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.signed_promo_grants import (
    DEVICE_CLAIM,
    GPU_CLAIM,
    PROMO_DECISION_KIND,
    PromoDecisionVerifier,
    PromoGrantDecisionError,
    SignedPromoGrantApplier,
    canonical_unsigned_envelope,
    promo_claim_id,
)


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class TestSignedPromoGrants(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.owners = OwnerAccountStore(root / "owners.sqlite3")
        self.ledger = OwnerCreditLedger(storage_path=root / "ledger.jsonl")
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
        self.verifier = PromoDecisionVerifier({"promo-key-1": self.public_key})
        self.applier = SignedPromoGrantApplier(
            owner_store=self.owners,
            ledger=self.ledger,
            verifier=self.verifier,
        )
        self.owners.ensure_owner("alice")
        self.owners.ensure_owner("bob")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _envelope(
        self,
        *,
        owner_id: str = "alice",
        claim_class: str = DEVICE_CLAIM,
        hardware_claim_id: str = "cmhw_v1_machine_a",
        node_id: str = "node-a",
        amount_micro_units: int = 25_000_000,
        policy_version: str = "onboarding-2026-09-v1",
        issued_at: int = 1_000,
        expires_at: int = 1_120,
        decision_id: str = "promo_dec_1",
    ) -> dict:
        claim_id = promo_claim_id(
            owner_id=owner_id,
            claim_class=claim_class,
            hardware_claim_id=hardware_claim_id,
            policy_version=policy_version,
        )
        unsigned = {
            "kind": PROMO_DECISION_KIND,
            "decision_id": decision_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "owner_id": owner_id,
            "claim_id": claim_id,
            "claim_class": claim_class,
            "hardware_claim_id": hardware_claim_id,
            "assurance_tier": "MULTI_SIGNAL_VERIFIED",
            "node_id": node_id,
            "amount_micro_units": amount_micro_units,
            "policy_version": policy_version,
            "evidence_digest": "sha256:" + "ab" * 32,
        }
        signature = self.private_key.sign(canonical_unsigned_envelope(unsigned))
        return {
            **unsigned,
            "signature": {
                "algorithm": "Ed25519",
                "key_id": "promo-key-1",
                "value": _b64u(signature),
            },
        }

    def _resign(self, envelope: dict) -> dict:
        unsigned = dict(envelope)
        unsigned.pop("signature", None)
        return {
            **unsigned,
            "signature": {
                "algorithm": "Ed25519",
                "key_id": "promo-key-1",
                "value": _b64u(self.private_key.sign(canonical_unsigned_envelope(unsigned))),
            },
        }

    def test_device_grant_is_claim_first_and_exactly_once(self) -> None:
        envelope = self._envelope()
        first = self.applier.apply(envelope, now=1_001)
        second = self.applier.apply(envelope, now=1_002)

        self.assertEqual(first.ledger_status, "credited")
        self.assertEqual(second.ledger_status, "already_credited")
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.promo_micro_units, 25_000_000)
        self.assertEqual(balances.withdrawable_micro_units, 0)
        self.assertIsNotNone(self.owners.promo_claim_for_owner("alice", DEVICE_CLAIM))
        self.assertEqual(
            self.owners.owner_for_device("cmhw_v1_machine_a"),
            "alice",
        )
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_existing_claim_without_ledger_grant_is_recovered(self) -> None:
        envelope = self._envelope(decision_id="promo_dec_recover")
        self.owners.bind_device(
            "alice",
            envelope["hardware_claim_id"],
            assurance_tier=envelope["assurance_tier"],
        )
        self.owners.record_promo_claim(
            claim_id=envelope["claim_id"],
            owner_id="alice",
            claim_class=DEVICE_CLAIM,
            hardware_claim_id=envelope["hardware_claim_id"],
            amount_micro_units=envelope["amount_micro_units"],
            policy_version=envelope["policy_version"],
        )
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 0)

        result = self.applier.apply(envelope, now=1_001)
        self.assertEqual(result.ledger_status, "credited")
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 25_000_000)

    def test_same_claim_with_new_delivery_decision_still_cannot_double_credit(self) -> None:
        first = self._envelope(decision_id="delivery-1")
        second = self._envelope(decision_id="delivery-2")
        self.applier.apply(first, now=1_001)
        result = self.applier.apply(second, now=1_002)
        self.assertEqual(result.ledger_status, "already_credited")
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 25_000_000)

    def test_gpu_grant_requires_provider_node_owned_by_same_owner(self) -> None:
        envelope = self._envelope(
            claim_class=GPU_CLAIM,
            node_id="rig-a",
            hardware_claim_id="cmhw_v1_gpu_machine_a",
            decision_id="gpu-1",
        )
        with self.assertRaisesRegex(PromoGrantDecisionError, "not bound"):
            self.applier.apply(envelope, now=1_001)

        self.owners.bind_provider_node("alice", "rig-a")
        result = self.applier.apply(envelope, now=1_001)
        self.assertEqual(result.claim_class, GPU_CLAIM)
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 25_000_000)

    def test_same_hardware_cannot_claim_for_second_owner(self) -> None:
        alice = self._envelope()
        self.applier.apply(alice, now=1_001)
        bob = self._envelope(
            owner_id="bob",
            hardware_claim_id=alice["hardware_claim_id"],
            decision_id="bob-attempt",
        )
        with self.assertRaises(PromoGrantDecisionError):
            self.applier.apply(bob, now=1_002)
        self.assertEqual(self.ledger.get_owner_balances("bob").promo_micro_units, 0)

    def test_expired_or_tampered_decision_fails_before_claim_or_credit(self) -> None:
        expired = self._envelope(decision_id="expired", expires_at=1_005)
        with self.assertRaisesRegex(PromoGrantDecisionError, "expired"):
            self.applier.apply(expired, now=1_005)

        tampered = self._envelope(decision_id="tampered")
        tampered["amount_micro_units"] = 50_000_000
        with self.assertRaisesRegex(PromoGrantDecisionError, "signature"):
            self.applier.apply(tampered, now=1_001)
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 0)
        self.assertIsNone(self.owners.promo_claim_for_owner("alice", DEVICE_CLAIM))

    def test_noncanonical_claim_id_is_rejected_even_when_signed(self) -> None:
        envelope = self._envelope(decision_id="wrong-claim")
        envelope["claim_id"] = "promo_claim_v1_notcanonical"
        envelope = self._resign(envelope)
        with self.assertRaisesRegex(PromoGrantDecisionError, "canonical"):
            self.applier.apply(envelope, now=1_001)

    def test_claim_class_cannot_be_reused_with_different_hardware_or_amount(self) -> None:
        first = self._envelope()
        self.applier.apply(first, now=1_001)
        second = self._envelope(
            hardware_claim_id="cmhw_v1_machine_b",
            amount_micro_units=20_000_000,
            decision_id="different-second-device",
        )
        with self.assertRaisesRegex(PromoGrantDecisionError, "already consumed"):
            self.applier.apply(second, now=1_002)
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 25_000_000)


if __name__ == "__main__":
    unittest.main()
