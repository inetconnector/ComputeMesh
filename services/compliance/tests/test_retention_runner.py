"""Unit tests for ComputeMesh Retention Lifecycle CLI Runner."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from scripts.run_retention_lifecycle import run_retention_lifecycle
from services.compliance.provider_identity import EntityType, IdentityVerificationState, ProviderIdentity, StructuredAddress
from services.compliance.provider_identity_store import ProviderIdentityStore


class TestRetentionRunner(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_identity.db")
        self.store = ProviderIdentityStore(storage_path=self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dry_run_execution(self) -> None:
        report = run_retention_lifecycle(
            db_path=self.db_path,
            dry_run=True,
        )
        self.assertEqual(report["status"], "success")
        self.assertTrue(report["dry_run"])
        self.assertTrue(report["results"]["dry_run_evaluated"])

    def test_skipped_non_existent_db(self) -> None:
        report = run_retention_lifecycle(
            db_path="/non/existent/path/db.sqlite",
            dry_run=False,
        )
        self.assertEqual(report["status"], "skipped")

    def test_active_retention_purge_cycle(self) -> None:
        # Create a draft record
        ident = self.store.upsert_identity(
            account_id="acc_draft_old",
            entity_type=EntityType.BUSINESS,
            legal_name="Old Draft Co",
            address=StructuredAddress(line1="Street 1", postal_code="10115", city="Berlin", country_code="DE"),
            email="draft@example.com",
        )
        # Set state to INCOMPLETE and created_at to old date (older than 90 days)
        old_time = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat().replace("+00:00", "Z")
        with self.store._connection() as conn:
            conn.execute(
                "UPDATE provider_identities SET verification_state = 'INCOMPLETE', created_at = ? WHERE account_id = ?",
                (old_time, "acc_draft_old"),
            )

        # Run retention lifecycle
        report = run_retention_lifecycle(
            db_path=self.db_path,
            dry_run=False,
        )
        self.assertEqual(report["status"], "success")
        self.assertFalse(report["dry_run"])
        self.assertGreaterEqual(report["results"]["purged_draft_profiles"], 1)

        # Verify draft was deleted
        retrieved = self.store.get_identity(ident.provider_identity_id)
        self.assertIsNone(retrieved)


if __name__ == "__main__":
    unittest.main()
