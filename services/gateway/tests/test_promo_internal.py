"""Tests for the internal private-policy/public-ledger promo bridge."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_credits import OwnerCreditLedger
from services.billing.signed_promo_grants import (
    DEVICE_CLAIM,
    PROMO_DECISION_KIND,
    canonical_unsigned_envelope,
    promo_claim_id,
)
from services.gateway.promo_internal import (
    PromoInternalError,
    PromoInternalService,
    build_promo_internal_service_from_env,
    load_trusted_promo_keys,
)


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class TestPromoInternalService(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.owners = OwnerAccountStore(root / "owners.sqlite3")
        self.ledger = OwnerCreditLedger(storage_path=root / "ledger.jsonl")
        self.owners.ensure_owner("alice")
        self.owners.ensure_owner("provider-owner")
        self.owners.bind_provider_node("provider-owner", "rig-1")
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.service = PromoInternalService(
            owner_store=self.owners,
            ledger=self.ledger,
            trusted_keys={"promo-key-1": self.public},
            bearer_token="promo-internal-token-long-enough-123",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _signed_device_grant(self, *, amount: int = 25_000_000) -> dict:
        policy = "onboarding-test-v1"
        hardware = "cmhw_v1_testmachine"
        claim_id = promo_claim_id(
            owner_id="alice",
            claim_class=DEVICE_CLAIM,
            hardware_claim_id=hardware,
            policy_version=policy,
        )
        unsigned = {
            "kind": PROMO_DECISION_KIND,
            "decision_id": "promo-dec-1",
            "issued_at": 1_000,
            "expires_at": 1_120,
            "owner_id": "alice",
            "claim_id": claim_id,
            "claim_class": DEVICE_CLAIM,
            "hardware_claim_id": hardware,
            "assurance_tier": "MULTI_SIGNAL_VERIFIED",
            "node_id": "node-1",
            "amount_micro_units": amount,
            "policy_version": policy,
            "evidence_digest": "sha256:" + "ab" * 32,
        }
        return {
            **unsigned,
            "signature": {
                "algorithm": "Ed25519",
                "key_id": "promo-key-1",
                "value": _b64u(self.private.sign(canonical_unsigned_envelope(unsigned))),
            },
        }

    def test_internal_auth_is_separate_constant_time_bearer_contract(self) -> None:
        self.assertTrue(
            self.service.authenticate("Bearer promo-internal-token-long-enough-123")
        )
        self.assertFalse(self.service.authenticate("Bearer wrong-token"))
        self.assertFalse(self.service.authenticate(""))

    def test_eligibility_returns_only_minimum_policy_state(self) -> None:
        view = self.service.eligibility({"owner_id": "alice", "node_id": "rig-1"})
        self.assertEqual(view.owner_id, "alice")
        self.assertEqual(view.current_owner_promo_micro_units, 0)
        self.assertEqual(view.already_claimed_classes, ())
        self.assertEqual(view.provider_node_owner_id, "provider-owner")
        self.assertEqual(
            set(view.to_dict()),
            {
                "owner_id",
                "current_owner_promo_micro_units",
                "already_claimed_classes",
                "provider_node_owner_id",
            },
        )

    def test_signed_grant_applies_exactly_once_and_updates_eligibility(self) -> None:
        envelope = self._signed_device_grant()
        first = self.service.apply(envelope, now=1_001)
        second = self.service.apply(envelope, now=1_002)
        self.assertEqual(first["ledger_status"], "credited")
        self.assertEqual(second["ledger_status"], "already_credited")
        view = self.service.eligibility({"owner_id": "alice"})
        self.assertEqual(view.current_owner_promo_micro_units, 25_000_000)
        self.assertEqual(view.already_claimed_classes, (DEVICE_CLAIM,))
        self.assertEqual(self.ledger.get_owner_balances("alice").withdrawable_micro_units, 0)

    def test_tampered_grant_is_rejected(self) -> None:
        envelope = self._signed_device_grant()
        envelope["amount_micro_units"] = 50_000_000
        with self.assertRaises(PromoInternalError):
            self.service.apply(envelope, now=1_001)
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, 0)

    def test_unknown_owner_and_extra_eligibility_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(PromoInternalError, "unknown owner"):
            self.service.eligibility({"owner_id": "missing"})
        with self.assertRaisesRegex(PromoInternalError, "contract"):
            self.service.eligibility({"owner_id": "alice", "email": "ignored@example.invalid"})

    def test_key_loader_is_bounded_and_strict(self) -> None:
        parsed = load_trusted_promo_keys(json.dumps({"promo-key-1": _b64u(self.public)}))
        self.assertEqual(parsed, {"promo-key-1": self.public})
        with self.assertRaises(PromoInternalError):
            load_trusted_promo_keys("[]")
        with self.assertRaises(PromoInternalError):
            load_trusted_promo_keys(json.dumps({"bad": "not+base64"}))


class TestPromoInternalEnvironment(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = {
            name: os.environ.get(name)
            for name in (
                "COMPUTEMESH_PROMO_INTERNAL_TOKEN",
                "COMPUTEMESH_PROMO_DECISION_PUBLIC_KEYS_JSON",
            )
        }
        for name in self.saved:
            os.environ.pop(name, None)
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.owners = OwnerAccountStore(root / "owners.sqlite3")
        self.ledger = OwnerCreditLedger(storage_path=root / "ledger.jsonl")

    def tearDown(self) -> None:
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp_dir.cleanup()

    def test_bridge_disabled_when_no_configuration_exists(self) -> None:
        self.assertIsNone(
            build_promo_internal_service_from_env(
                owner_store=self.owners,
                ledger=self.ledger,
            )
        )

    def test_partial_configuration_fails_startup(self) -> None:
        os.environ["COMPUTEMESH_PROMO_INTERNAL_TOKEN"] = "x" * 32
        with self.assertRaisesRegex(RuntimeError, "requires both"):
            build_promo_internal_service_from_env(
                owner_store=self.owners,
                ledger=self.ledger,
            )

    def test_complete_configuration_builds_service(self) -> None:
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        os.environ["COMPUTEMESH_PROMO_INTERNAL_TOKEN"] = "x" * 32
        os.environ["COMPUTEMESH_PROMO_DECISION_PUBLIC_KEYS_JSON"] = json.dumps(
            {"promo-key-1": _b64u(public)}
        )
        service = build_promo_internal_service_from_env(
            owner_store=self.owners,
            ledger=self.ledger,
        )
        self.assertIsInstance(service, PromoInternalService)


if __name__ == "__main__":
    unittest.main()
