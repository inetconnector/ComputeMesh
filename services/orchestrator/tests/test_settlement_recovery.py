from __future__ import annotations

import unittest

from services.gateway.cancellable_inference import CancellableInferenceEngine
from services.gateway.inference_backend import BackendResult
from services.orchestrator.settlement_recovery import (
    acknowledge_job_settlement,
    reconcile_completed_settlements,
)
from services.orchestrator.startup_recovery import RecoveryStateStore
from services.orchestrator.state_machine import JobState


class _LedgerView:
    def __init__(self, events=()):
        self._processed_events = set(events)


class _BillingLedger(_LedgerView):
    def __init__(self):
        super().__init__()
        self.recorded = []
        self._holds = {}
        self._hold_seq = 0

    def get_balance(self, account_id):
        return 1_000_000

    def get_available_balance(self, account_id):
        return 1_000_000

    def create_hold(self, *, account_id, amount_micro_units, model_id, ttl_seconds=300):
        import time
        from services.billing.ledger import CreditHold
        self._hold_seq += 1
        hold_id = f"hold_{self._hold_seq}"
        hold = CreditHold(
            hold_id=hold_id,
            account_id=account_id,
            amount_micro_units=amount_micro_units,
            model_id=model_id,
            created_at=time.time(),
            expires_at=time.time() + ttl_seconds,
            status="active",
        )
        self._holds[hold_id] = hold
        return hold

    def release_hold(self, hold_id):
        if hold_id in self._holds:
            self._holds[hold_id].status = "released"
            return True
        return False

    def capture_hold(self, *, hold_id, job_id, customer_account_id, provider_shares, model_id, prompt_tokens, completion_tokens, network_fee_bps=None):
        if hold_id in self._holds:
            self._holds[hold_id].status = "captured"
        return self.record_job_execution(
            job_id=job_id,
            customer_account_id=customer_account_id,
            provider_shares=provider_shares,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            network_fee_bps=network_fee_bps,
        )

    def record_job_execution(self, **kwargs):
        self.recorded.append(kwargs)
        self._processed_events.add("job:" + kwargs["job_id"])
        return object()


class _Metrics:
    def record_request(self, **kwargs):
        pass


class _Teaser:
    pass


def _complete_job(store: RecoveryStateStore, job_id: str) -> None:
    store.ensure_job(job_id)
    for target in (
        JobState.VALIDATING,
        JobState.PLANNING,
        JobState.RESERVING,
        JobState.PREPARING,
        JobState.RUNNING,
        JobState.VERIFYING,
        JobState.COMPLETED,
    ):
        current = store.get_job(job_id)
        store.transition_job(
            job_id,
            request_id=f"advance:{job_id}:{target.value}",
            expected_revision=current.revision,
            target=target,
        )


class _CompletedBackend:
    def __init__(self, store: RecoveryStateStore, job_id: str):
        self.store = store
        self.job_id = job_id

    def complete(self, *, model_id, messages):
        return BackendResult(
            "done",
            2,
            3,
            execution_job_id=self.job_id,
            provider_shares=(("node-a", 0.5), ("node-b", 0.5)),
        )


class SettlementRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.store = RecoveryStateStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_acknowledge_moves_only_completed_to_settled(self):
        _complete_job(self.store, "job-1")
        self.assertTrue(acknowledge_job_settlement(self.store, "job-1"))
        self.assertEqual(self.store.get_job("job-1").state, JobState.SETTLED)
        self.assertFalse(acknowledge_job_settlement(self.store, "job-1"))

    def test_startup_repairs_ledger_commit_before_ack_window(self):
        _complete_job(self.store, "job-billed")
        _complete_job(self.store, "job-unbilled")
        ledger = _LedgerView({"job:job-billed"})

        report = reconcile_completed_settlements(self.store, ledger)

        self.assertEqual(self.store.get_job("job-billed").state, JobState.SETTLED)
        self.assertEqual(self.store.get_job("job-unbilled").state, JobState.COMPLETED)
        self.assertEqual(report.settled_jobs, ("job-billed",))
        self.assertEqual(report.pending_jobs, ("job-unbilled",))

    def test_live_engine_acks_only_after_ledger_record_succeeds(self):
        _complete_job(self.store, "job-live")
        ledger = _BillingLedger()
        engine = CancellableInferenceEngine(
            ledger=ledger,
            metrics=_Metrics(),
            teaser_manager=_Teaser(),
            backend=_CompletedBackend(self.store, "job-live"),
        )

        engine.create_metered_completion(
            account_id="acct",
            model_id="qwen/qwen2.5-7b-instruct",
            messages=[{"role": "user", "content": "hi"}],
        )

        self.assertEqual(ledger.recorded[0]["job_id"], "job-live")
        self.assertEqual(self.store.get_job("job-live").state, JobState.SETTLED)

    def test_failed_ledger_write_does_not_settle_job(self):
        _complete_job(self.store, "job-fail")

        class FailingLedger(_BillingLedger):
            def record_job_execution(self, **kwargs):
                raise RuntimeError("disk failure")

        engine = CancellableInferenceEngine(
            ledger=FailingLedger(),
            metrics=_Metrics(),
            teaser_manager=_Teaser(),
            backend=_CompletedBackend(self.store, "job-fail"),
        )
        with self.assertRaises(RuntimeError):
            engine.create_metered_completion(
                account_id="acct",
                model_id="qwen/qwen2.5-7b-instruct",
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(self.store.get_job("job-fail").state, JobState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
