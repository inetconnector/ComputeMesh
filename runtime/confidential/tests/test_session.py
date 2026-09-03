from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from protocol.confidential_metering import generate_attested_metering_keypair
from protocol.confidential_envelope import generate_attested_recipient_keypair
from runtime.confidential.data_plane import AttestedConfidentialEndpoint
from runtime.confidential.session import (
    ConfidentialSessionProvision,
    ConfidentialSessionStateError,
    SQLiteConfidentialSessionStore,
)


class ConfidentialSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "sessions.sqlite3"
        self.store = SQLiteConfidentialSessionStore(self.path)
        _, recipient_public = generate_attested_recipient_keypair()
        _, metering_public = generate_attested_metering_keypair()
        self.expires = datetime.now(UTC) + timedelta(minutes=5)
        self.endpoint = AttestedConfidentialEndpoint(
            url="https://tee.example/v1/confidential/execute",
            node_id="node-1",
            runtime_digest="sha256:runtime",
            attestation_nonce="nonce-1",
            recipient_public_key=recipient_public,
            metering_public_key=metering_public,
            tls_certificate_sha256="sha256:" + "a" * 64,
        )
        self.attestation = {
            "schema_version": 1,
            "node_id": "node-1",
            "technology": "test-tee",
            "measurement": "measurement",
            "runtime_digest": "sha256:runtime",
            "ephemeral_public_key": recipient_public,
            "metering_public_key": metering_public,
            "data_plane_tls_sha256": "sha256:" + "a" * 64,
            "nonce": "nonce-1",
            "issued_at": datetime.now(UTC).isoformat(),
            "expires_at": self.expires.isoformat(),
            "debug_disabled": True,
        }
        self.provision = ConfidentialSessionProvision(
            job_id="job-1",
            account_id="acct-1",
            model_id="qwen/qwen2.5-7b-instruct",
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=4096,
            max_completion_tokens=512,
            endpoint=self.endpoint,
            attestation=self.attestation,
            expires_at=self.expires.isoformat(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_persists_only_content_free_admission_state(self) -> None:
        created = self.store.create(self.provision, hold_id="hold-1")
        self.assertEqual(created.state, "OPEN")
        loaded = self.store.get("job-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.endpoint.metering_public_key, self.endpoint.metering_public_key)
        with sqlite3.connect(self.path) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(confidential_sessions)")]
        self.assertNotIn("prompt", columns)
        self.assertNotIn("output", columns)
        self.assertNotIn("ciphertext", columns)

    def test_public_descriptor_contains_attestation_but_no_private_ranking_state(self) -> None:
        descriptor = self.provision.public_descriptor()
        self.assertEqual(descriptor["recipient_public_key"], self.endpoint.recipient_public_key)
        self.assertEqual(descriptor["metering_public_key"], self.endpoint.metering_public_key)
        encoded = repr(descriptor).lower()
        self.assertNotIn("score", encoded)
        self.assertNotIn("price_coefficient", encoded)
        self.assertNotIn("candidate", encoded)

    def test_attestation_key_or_endpoint_substitution_is_rejected(self) -> None:
        broken_attestation = dict(self.attestation)
        broken_attestation["metering_public_key"] = "attacker"
        broken = ConfidentialSessionProvision(
            **{**self.provision.__dict__, "attestation": broken_attestation}
        )
        with self.assertRaisesRegex(Exception, "metering key"):
            broken.validate()

    def test_dispatch_is_single_winner_for_same_job(self) -> None:
        self.store.create(self.provision, hold_id="hold-1")

        def attempt(index: int) -> str:
            store = SQLiteConfidentialSessionStore(self.path)
            try:
                store.begin_dispatch(
                    job_id="job-1",
                    account_id="acct-1",
                    envelope_id=f"{index:032x}",
                )
                return "won"
            except ConfidentialSessionStateError:
                return "lost"

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(results.count("won"), 1)
        self.assertEqual(results.count("lost"), 7)
        record = self.store.get("job-1")
        self.assertEqual(record.state, "DISPATCHED")
        self.assertIsNotNone(record.envelope_id)

    def test_wrong_account_cannot_dispatch(self) -> None:
        self.store.create(self.provision, hold_id="hold-1")
        with self.assertRaisesRegex(ConfidentialSessionStateError, "account"):
            self.store.begin_dispatch(
                job_id="job-1",
                account_id="acct-attacker",
                envelope_id="a" * 32,
            )
        self.assertEqual(self.store.get("job-1").state, "OPEN")

    def test_expired_session_fails_closed_and_is_marked_expired(self) -> None:
        expired_at = datetime(2026, 1, 1, tzinfo=UTC)
        provision = ConfidentialSessionProvision(
            **{**self.provision.__dict__, "expires_at": expired_at.isoformat()}
        )
        # Provision validation permits an expired timestamp structurally; dispatch owns freshness.
        self.store.create(provision, hold_id="hold-1")
        with self.assertRaisesRegex(ConfidentialSessionStateError, "expired"):
            self.store.begin_dispatch(
                job_id="job-1",
                account_id="acct-1",
                envelope_id="a" * 32,
                now=datetime(2026, 2, 1, tzinfo=UTC),
            )
        self.assertEqual(self.store.get("job-1").state, "EXPIRED")

    def test_only_dispatched_session_can_complete_or_fail(self) -> None:
        self.store.create(self.provision, hold_id="hold-1")
        with self.assertRaisesRegex(ConfidentialSessionStateError, "terminal"):
            self.store.finish(job_id="job-1", target="COMPLETED")
        self.store.begin_dispatch(
            job_id="job-1",
            account_id="acct-1",
            envelope_id="a" * 32,
        )
        completed = self.store.finish(job_id="job-1", target="COMPLETED")
        self.assertEqual(completed.state, "COMPLETED")
        with self.assertRaises(ConfidentialSessionStateError):
            self.store.finish(job_id="job-1", target="FAILED")

    def test_in_memory_store_is_forbidden(self) -> None:
        with self.assertRaisesRegex(ValueError, "durable"):
            SQLiteConfidentialSessionStore(":memory:")


if __name__ == "__main__":
    unittest.main()
