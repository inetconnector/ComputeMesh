"""Tests for durable owner/resource mappings and promo claims."""
from pathlib import Path
import tempfile
import unittest

from services.billing.owner_accounts import (
    OwnerAccountStore,
    OwnerAccountStoreError,
    PROMO_DEVICE,
    PROMO_GPU,
)


class TestOwnerAccountStore(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = OwnerAccountStore(Path(self.temp_dir.name) / "owners.sqlite3")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_one_owner_can_bind_multiple_api_keys_and_rigs(self) -> None:
        self.store.ensure_owner("alice", display_name="Alice")
        self.store.bind_api_credential("alice", "api-key-id-1")
        self.store.bind_api_credential("alice", "api-key-id-2")
        self.store.bind_provider_node("alice", "rig-01")
        self.store.bind_provider_node("alice", "rig-02")

        self.assertEqual(self.store.owner_for_api_credential("api-key-id-1"), "alice")
        self.assertEqual(self.store.owner_for_api_credential("api-key-id-2"), "alice")
        self.assertEqual(self.store.owner_for_provider_node("rig-01"), "alice")
        self.assertEqual(self.store.list_provider_nodes("alice"), ["rig-01", "rig-02"])

    def test_provider_node_cannot_silently_move_to_another_owner(self) -> None:
        self.store.ensure_owner("alice")
        self.store.ensure_owner("bob")
        self.store.bind_provider_node("alice", "rig-01")
        with self.assertRaises(OwnerAccountStoreError):
            self.store.bind_provider_node("bob", "rig-01")

    def test_device_claim_is_owner_bound_but_assurance_can_update(self) -> None:
        self.store.ensure_owner("alice")
        self.store.bind_device("alice", "cmhw-abc", assurance_tier="UNVERIFIED")
        self.store.bind_device("alice", "cmhw-abc", assurance_tier="HARDWARE_ATTESTED")
        self.assertEqual(self.store.owner_for_device("cmhw-abc"), "alice")

    def test_promo_claim_is_idempotent_for_same_claim_id(self) -> None:
        self.store.ensure_owner("alice")
        claim = self.store.record_promo_claim(
            claim_id="promo-alice-device-v1",
            owner_id="alice",
            claim_class=PROMO_DEVICE,
            hardware_claim_id="cmhw-abc",
            amount_micro_units=25_000_000,
            policy_version="onboarding-v1",
        )
        retry = self.store.record_promo_claim(
            claim_id="promo-alice-device-v1",
            owner_id="alice",
            claim_class=PROMO_DEVICE,
            hardware_claim_id="cmhw-abc",
            amount_micro_units=25_000_000,
            policy_version="onboarding-v1",
        )
        self.assertEqual(claim, retry)

    def test_owner_cannot_claim_same_promo_stage_twice(self) -> None:
        self.store.ensure_owner("alice")
        self.store.record_promo_claim(
            claim_id="claim-1",
            owner_id="alice",
            claim_class=PROMO_GPU,
            hardware_claim_id="gpu-proof-1",
            amount_micro_units=25_000_000,
            policy_version="onboarding-v1",
        )
        with self.assertRaises(OwnerAccountStoreError):
            self.store.record_promo_claim(
                claim_id="claim-2",
                owner_id="alice",
                claim_class=PROMO_GPU,
                hardware_claim_id="gpu-proof-2",
                amount_micro_units=25_000_000,
                policy_version="onboarding-v1",
            )

    def test_same_hardware_cannot_fund_same_promo_for_two_owners(self) -> None:
        self.store.ensure_owner("alice")
        self.store.ensure_owner("bob")
        self.store.record_promo_claim(
            claim_id="alice-device",
            owner_id="alice",
            claim_class=PROMO_DEVICE,
            hardware_claim_id="cmhw-shared",
            amount_micro_units=25_000_000,
            policy_version="onboarding-v1",
        )
        with self.assertRaises(OwnerAccountStoreError):
            self.store.record_promo_claim(
                claim_id="bob-device",
                owner_id="bob",
                claim_class=PROMO_DEVICE,
                hardware_claim_id="cmhw-shared",
                amount_micro_units=25_000_000,
                policy_version="onboarding-v1",
            )


if __name__ == "__main__":
    unittest.main()
