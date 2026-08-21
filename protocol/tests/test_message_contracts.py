import unittest

from protocol.message_contracts import MessageContractError, MessageContractValidator


class MessageContractTests(unittest.TestCase):
    def setUp(self):
        self.validator = MessageContractValidator()

    def test_exact_initial_handler_set(self):
        self.assertEqual(
            self.validator.supported_messages(),
            frozenset({"ReserveCapacity", "CommitReservation", "CancelJob"}),
        )

    def test_reserve_capacity_requires_lease_expiry(self):
        self.validator.validate(
            "ReserveCapacity",
            {"lease_expires_at": "2026-08-21T12:00:00Z"},
        )
        with self.assertRaises(MessageContractError):
            self.validator.validate("ReserveCapacity", {})

    def test_commit_reservation_requires_job_and_stage(self):
        self.validator.validate(
            "CommitReservation",
            {"job_id": "job-1", "stage_id": "stage-1"},
        )
        with self.assertRaises(MessageContractError):
            self.validator.validate("CommitReservation", {"job_id": "job-1"})

    def test_cancel_job_requires_cutoff_policy(self):
        self.validator.validate(
            "CancelJob",
            {
                "reason": "user_request",
                "cutoff_policy": "stop_new_billable_work",
            },
        )
        with self.assertRaises(MessageContractError):
            self.validator.validate("CancelJob", {"reason": "user_request"})

    def test_unknown_message_is_not_silently_accepted(self):
        with self.assertRaises(KeyError):
            self.validator.validate("ValidateJob", {})


if __name__ == "__main__":
    unittest.main()
