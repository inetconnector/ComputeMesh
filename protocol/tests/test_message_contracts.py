import unittest

from protocol.message_contracts import MessageContractError, MessageContractValidator


class MessageContractTests(unittest.TestCase):
    def setUp(self):
        self.validator = MessageContractValidator()

    def test_expected_messages_are_registered(self):
        supported = self.validator.supported_messages()
        self.assertIn("ReserveCapacity", supported)
        self.assertIn("CommitReservation", supported)
        self.assertIn("CancelJob", supported)

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

    def test_empty_internal_payload_rejects_unknown_fields(self):
        self.validator.validate("ValidateJob", {})
        with self.assertRaises(MessageContractError):
            self.validator.validate("ValidateJob", {"arbitrary": True})

    def test_unknown_message_is_not_silently_accepted(self):
        with self.assertRaises(KeyError):
            self.validator.validate("ArbitraryCommand", {})


if __name__ == "__main__":
    unittest.main()
