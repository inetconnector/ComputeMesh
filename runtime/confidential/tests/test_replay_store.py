from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    encrypt_for_attested_recipient,
    generate_attested_recipient_keypair,
)
from runtime.confidential.replay_store import (
    ConfidentialReplayBindingError,
    ConfidentialReplayDetected,
    SQLiteConfidentialReplayStore,
)


class ConfidentialReplayStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "replay.sqlite3"
        self.store = SQLiteConfidentialReplayStore(self.db_path)
        _, recipient_public = generate_attested_recipient_keypair()
        self.binding = ConfidentialBinding(
            account_id="acct-1",
            job_id="job-1",
            node_id="node-1",
            attestation_nonce="nonce-1",
            runtime_digest="sha256:runtime",
            data_plane_tls_sha256="sha256:" + "a" * 64,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
        )
        self.envelope = encrypt_for_attested_recipient(
            b"SECRET-PROMPT-NEVER-PERSIST",
            recipient_public_key=recipient_public,
            binding=self.binding,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _claim(self):
        return self.store.claim(
            self.envelope,
            expected_account_id="acct-1",
            expected_privacy_class="CONFIDENTIAL",
            expected_operation="chat_completion",
        )

    def test_first_claim_succeeds_second_claim_is_replay(self) -> None:
        claim = self._claim()
        self.assertEqual(claim.envelope_id, self.envelope.envelope_id)
        with self.assertRaisesRegex(ConfidentialReplayDetected, "already consumed"):
            self._claim()
        stored = self.store.get_claim(self.envelope.envelope_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.account_id, "acct-1")

    def test_binding_mismatch_does_not_consume_envelope(self) -> None:
        with self.assertRaisesRegex(ConfidentialReplayBindingError, "account"):
            self.store.claim(
                self.envelope,
                expected_account_id="acct-attacker",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
            )
        self.assertIsNone(self.store.get_claim(self.envelope.envelope_id))
        self._claim()

    def test_privacy_and_operation_downgrade_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfidentialReplayBindingError, "privacy"):
            self.store.claim(
                self.envelope,
                expected_account_id="acct-1",
                expected_privacy_class="CRYPTO_PRIVATE",
                expected_operation="chat_completion",
            )
        with self.assertRaisesRegex(ConfidentialReplayBindingError, "operation"):
            self.store.claim(
                self.envelope,
                expected_account_id="acct-1",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="ollama_chat",
            )

    def test_concurrent_claim_has_exactly_one_winner(self) -> None:
        def attempt(_: int) -> str:
            other = SQLiteConfidentialReplayStore(self.db_path)
            try:
                other.claim(
                    self.envelope,
                    expected_account_id="acct-1",
                    expected_privacy_class="CONFIDENTIAL",
                    expected_operation="chat_completion",
                )
                return "won"
            except ConfidentialReplayDetected:
                return "replay"

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(results.count("won"), 1)
        self.assertEqual(results.count("replay"), 7)

    def test_plaintext_and_ciphertext_are_not_stored(self) -> None:
        self._claim()
        with sqlite3.connect(self.db_path) as connection:
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(confidential_replay_claims)")
            ]
            row = connection.execute(
                "SELECT * FROM confidential_replay_claims WHERE envelope_id = ?",
                (self.envelope.envelope_id,),
            ).fetchone()
        self.assertNotIn("ciphertext", columns)
        self.assertNotIn("prompt", columns)
        encoded_row = repr(row)
        self.assertNotIn("SECRET-PROMPT-NEVER-PERSIST", encoded_row)
        self.assertNotIn(self.envelope.ciphertext, encoded_row)

    def test_memory_database_is_rejected_because_replay_state_must_survive_restart(self) -> None:
        with self.assertRaisesRegex(ValueError, "durable"):
            SQLiteConfidentialReplayStore(":memory:")

    def test_purge_is_explicit_operator_action(self) -> None:
        self.store.claim(
            self.envelope,
            expected_account_id="acct-1",
            expected_privacy_class="CONFIDENTIAL",
            expected_operation="chat_completion",
            now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        deleted = self.store.purge_before(datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(deleted, 1)
        self.assertIsNone(self.store.get_claim(self.envelope.envelope_id))


if __name__ == "__main__":
    unittest.main()
