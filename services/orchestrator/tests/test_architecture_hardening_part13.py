import pytest
import sqlite3
import tempfile
import os
from datetime import datetime, timezone

from services.orchestrator.architecture_hardening_part13 import (
    ExplicitRetryEnforcer,
    CommandExpirationEnforcer,
    EventDeduplicator,
    ImplicitRetryError,
    CommandExpiredError,
    DuplicateEventError
)
from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.state_machine import JobState

def test_explicit_retry_enforcer():
    db = sqlite3.connect(":memory:")
    enforcer = ExplicitRetryEnforcer(db)
    enforcer.register_attempt("job1", 1)
    enforcer.register_attempt("job1", 2)

    with pytest.raises(ImplicitRetryError):
        enforcer.register_attempt("job1", 2)

    with pytest.raises(ImplicitRetryError):
        enforcer.register_attempt("job1", 1)

def test_command_expiration_enforcer():
    enforcer = CommandExpirationEnforcer()
    current_time = 100.0

    # Valid command
    enforcer.validate_command({"expires_at": 150.0}, current_time)

    # Expired command
    with pytest.raises(CommandExpiredError):
        enforcer.validate_command({"expires_at": 90.0}, current_time)

    # Command without expiration
    with pytest.raises(CommandExpiredError):
        enforcer.validate_command({}, current_time)

def test_event_deduplicator():
    db = sqlite3.connect(":memory:")
    dedup = EventDeduplicator(db)

    assert dedup.process_event("event1") is True
    assert dedup.process_event("event2") is True

    assert dedup.process_event("event1") is False

    with pytest.raises(ValueError):
        dedup.process_event("")

def test_persistence_deduplicator():
    with tempfile.TemporaryDirectory() as td:
        store = SQLiteStateStore(os.path.join(td, "state.db"))
        job = store.ensure_job("job1")

        # Valid transition
        store.transition_job(
            "job1",
            request_id="req1",
            expected_revision=job.revision,
            target=JobState.VALIDATING,
        )

def test_persistence_command_expiration():
    with tempfile.TemporaryDirectory() as td:
        store = SQLiteStateStore(os.path.join(td, "state.db"))
        job = store.ensure_job("job2")

        now = datetime.now(timezone.utc).timestamp()
        expired_metadata = {"expires_at": now - 100}

        # Expired command should raise
        with pytest.raises(CommandExpiredError):
            store.transition_job(
                "job2",
                request_id="req2",
                expected_revision=job.revision,
                target=JobState.VALIDATING,
                command_metadata=expired_metadata
            )

        # Valid command should pass
        valid_metadata = {"expires_at": now + 100}
        store.transition_job(
            "job2",
            request_id="req3",
            expected_revision=job.revision,
            target=JobState.VALIDATING,
            command_metadata=valid_metadata
        )

def test_persistence_explicit_retry():
    with tempfile.TemporaryDirectory() as td:
        store = SQLiteStateStore(os.path.join(td, "state.db"))
        job = store.ensure_job("job3")

        # First attempt
        store.transition_job(
            "job3",
            request_id="req4",
            expected_revision=job.revision,
            target=JobState.VALIDATING,
            attempt_number=1
        )

        job = store.get_job("job3")

        # Implicit retry (same attempt number) should fail
        with pytest.raises(ImplicitRetryError):
            store.transition_job(
                "job3",
                request_id="req5",
                expected_revision=job.revision,
                target=JobState.PLANNING,
                attempt_number=1
            )

        # Explicit retry (higher attempt number) should pass
        store.transition_job(
            "job3",
            request_id="req6",
            expected_revision=job.revision,
            target=JobState.PLANNING,
            attempt_number=2
        )
