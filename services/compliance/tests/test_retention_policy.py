"""Unit tests for Retention Policy engine and statutory lifecycle execution."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from services.compliance.provider_identity import (
    EntityType,
    StructuredAddress,
)
from services.compliance.provider_identity_store import ProviderIdentityStore
from services.compliance.retention_policy import (
    RetentionAction,
    RetentionCategory,
    RetentionEngine,
)


class RetentionPolicyTests(unittest.TestCase):

    def test_zero_disk_inference_retention_rule(self) -> None:
        """Inference streams have zero duration retention and immediate memory purge."""
        rule = RetentionEngine.get_rule(RetentionCategory.PROMPT_INFERENCE_DATA)
        self.assertEqual(rule.duration_days, 0)
        self.assertEqual(rule.action, RetentionAction.PURGE_IMMEDIATELY)
        self.assertTrue(rule.is_expired("2026-09-08T12:00:00Z"))

    def test_dsa_trader_record_retention_rule(self) -> None:
        """DSA Art. 30(5) statutory rule specifies 180 days (6 months) retention post-termination."""
        rule = RetentionEngine.get_rule(RetentionCategory.DSA_TRADER_RECORDS)
        self.assertEqual(rule.duration_days, 180)
        self.assertEqual(rule.action, RetentionAction.DELETE)

        now = datetime.now(timezone.utc)
        recent_termination = (now - timedelta(days=30)).isoformat()
        old_termination = (now - timedelta(days=200)).isoformat()

        self.assertFalse(rule.is_expired(recent_termination, now=now))
        self.assertTrue(rule.is_expired(old_termination, now=now))

    def test_inactive_draft_profile_purging(self) -> None:
        """Inactive draft profiles older than 90 days with no bound fleets are purged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProviderIdentityStore(Path(tmpdir) / "retention_test.db")
            now = datetime.now(timezone.utc)

            # Create an active/fresh draft
            store.upsert_identity(
                account_id="acc_fresh",
                entity_type=EntityType.INDIVIDUAL,
                legal_name="Fresh Provider",
                address=StructuredAddress(line1="Musterstr 1", city="Berlin", postal_code="10115", country_code="DE"),
                email="fresh@example.com",
            )

            # Manually insert a stale draft created 100 days ago
            stale_created = (now - timedelta(days=100)).isoformat().replace("+00:00", "Z")
            with store._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO provider_identities(
                        provider_identity_id, account_id, entity_type, legal_name,
                        address_line1, postal_code, city, country_code, email,
                        verification_state, created_at, updated_at, schema_version
                    ) VALUES('prv_stale', 'acc_stale', 'individual', 'Stale Draft',
                             'Old Road 1', '12345', 'Oldtown', 'DE', 'stale@example.com',
                             'INCOMPLETE', ?, ?, 2)
                    """,
                    (stale_created, stale_created),
                )

            # Apply lifecycle
            results = store.apply_retention_lifecycle(now=now)
            self.assertEqual(results["purged_draft_profiles"], 1)

            self.assertIsNone(store.get_identity("prv_stale"))
            self.assertIsNotNone(store.get_identity_by_account("acc_fresh"))


if __name__ == "__main__":
    unittest.main()
