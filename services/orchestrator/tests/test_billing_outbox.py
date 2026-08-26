from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from services.billing.threadsafe_ledger import ThreadSafeLedger
from services.gateway.cancellable_inference import RequestContextBackend
from services.gateway.inference_backend import BackendResult
from services.orchestrator.billing_intent import (
    BillingIntentConflict,
    BillingIntentStore,
    record_intent_exact,
)
from services.orchestrator.settlement_recovery import replay_billing_outbox
from services.orchestrator.startup_recovery import RecoveryStateStore
from services.orchestrator.state_machine import JobState


_FORWARD = (
    JobState.VALIDATING,
    JobState.PLANNING,
    JobState.RESERVING,
    JobState.PREPARING,
    JobState.RUNNING,
    JobState.VERIFYING,
    JobState.COMPLETED,
)


def complete_job(store: RecoveryStateStore, job_id: str) -> None:
    store.ensure_job(job_id)
    for state in _FORWARD:
        current = store.get_job(job_id)
        store.transition_job(
            job_id,
            request_id=f"test:{job_id}:{state.value}",
            expected_revision=current.revision,
            target=state,
        )


class _CompletedBackend:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def complete(self, *, model_id, messages):
        return BackendResult(
            "ok",
            3,
            5,
            execution_job_id=self.job_id,
            provider_shares=(("node-a", 0.4), ("node-b", 0.6)),
        )


class BillingOutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state_path = root / "state.sqlite"
        self.ledger_path = root / "ledger.jsonl"
        self.store = RecoveryStateStore(self.state_path)
        self.ledger = ThreadSafeLedger(storage_path=self.ledger_path, network_fee_bps=2500)
        self.ledger.deposit_customer_credits(
            customer_account_id="acct",
            amount_micro_units=10_000_000,
            payment_reference="seed",
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _intent(self, job_id: str = "job-1"):
        complete_job(self.store, job_id)
        intents = BillingIntentStore(self.store)
        intent = intents.put_pending(
            job_id=job_id,
            account_id="acct",
            model_id="frozen-model",
            prompt_tokens=3,
            completion_tokens=5,
            provider_shares=(("node-a", 0.4), ("node-b", 0.6)),
            network_fee_bps=2000,
            prompt_micro_per_token=111,
            completion_micro_per_token=777,
        )
        intents.close()
        return intent

    def test_replays_crash_after_intent_before_ledger(self):
        intent = self._intent()
        self.assertNotIn("job:job-1", self.ledger._processed_events)

        report = replay_billing_outbox(self.store, self.ledger)

        self.assertEqual(report.replayed_jobs, ("job-1",))
        self.assertEqual(self.store.get_job("job-1").state, JobState.SETTLED)
        self.assertIn("job:job-1", self.ledger._processed_events)
        self.assertEqual(self.ledger.get_balance("acct"), 10_000_000 - intent.total_charge_micro_units)
        # Exact frozen prices are used; current catalog pricing is irrelevant.
        self.assertEqual(intent.total_charge_micro_units, 3 * 111 + 5 * 777)
        self.assertEqual(BillingIntentStore(self.store).get("job-1").status, "RECORDED")

    def test_repairs_crash_after_ledger_before_outbox_ack(self):
        intent = self._intent("job-ledger-first")
        record_intent_exact(self.ledger, intent)

        report = replay_billing_outbox(self.store, self.ledger)

        self.assertEqual(report.repaired_recorded_jobs, ("job-ledger-first",))
        self.assertEqual(report.replayed_jobs, ())
        self.assertEqual(self.store.get_job("job-ledger-first").state, JobState.SETTLED)

    def test_replay_is_idempotent(self):
        self._intent("job-idempotent")
        first = replay_billing_outbox(self.store, self.ledger)
        count = len(self.ledger._transactions)
        second = replay_billing_outbox(self.store, self.ledger)
        self.assertEqual(first.replayed_jobs, ("job-idempotent",))
        self.assertEqual(second.replayed_jobs, ())
        self.assertEqual(len(self.ledger._transactions), count)

    def test_same_job_rejects_changed_billing_payload(self):
        self._intent("job-conflict")
        intents = BillingIntentStore(self.store)
        with self.assertRaises(BillingIntentConflict):
            intents.put_pending(
                job_id="job-conflict",
                account_id="different-account",
                model_id="frozen-model",
                prompt_tokens=3,
                completion_tokens=5,
                provider_shares=(("node-a", 0.4), ("node-b", 0.6)),
                network_fee_bps=2000,
                prompt_micro_per_token=111,
                completion_micro_per_token=777,
            )
        intents.close()

    def test_request_backend_persists_intent_before_returning_to_billing(self):
        complete_job(self.store, "job-pre-ledger")
        intents = BillingIntentStore(self.store)
        import threading
        local = threading.local()
        local.billing_context = {
            "account_id": "acct",
            "model_id": "frozen-model",
            "network_fee_bps": 1234,
            "prompt_micro_per_token": 10,
            "completion_micro_per_token": 20,
        }
        wrapped = RequestContextBackend(_CompletedBackend("job-pre-ledger"), local, intents)

        result = wrapped.complete(model_id="frozen-model", messages=[{"role": "user", "content": "x"}])

        self.assertEqual(result.execution_job_id, "job-pre-ledger")
        self.assertNotIn("job:job-pre-ledger", self.ledger._processed_events)
        saved = intents.get("job-pre-ledger")
        self.assertEqual(saved.status, "PENDING")
        self.assertEqual(saved.total_charge_micro_units, 3 * 10 + 5 * 20)
        intents.close()


if __name__ == "__main__":
    unittest.main()
