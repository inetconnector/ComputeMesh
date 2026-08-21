from datetime import datetime, timedelta, timezone
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from protocol import ProtocolFault, parse_control_envelope


class ControlEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
        self.base = {
            "protocol_major": 0,
            "protocol_minor": 2,
            "message_type": "CancelJob",
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "actor_id": "service-orchestrator",
            "target_id": "job-1",
            "issued_at": (self.now - timedelta(seconds=1)).isoformat(),
            "expires_at": (self.now + timedelta(seconds=30)).isoformat(),
            "expected_revision": 3,
            "payload": {"reason": "client_cancelled"},
        }

    def test_valid_envelope(self):
        parsed = parse_control_envelope(self.base, now=self.now)
        self.assertEqual(parsed.message_type, "CancelJob")
        self.assertEqual(parsed.expected_revision, 3)
        self.assertEqual(parsed.to_dict()["request_id"], "req-1")

    def test_higher_minor_is_base_envelope_compatible(self):
        doc = dict(self.base, protocol_minor=99)
        self.assertEqual(parse_control_envelope(doc, now=self.now).protocol_minor, 99)

    def test_unsupported_major_rejected(self):
        doc = dict(self.base, protocol_major=1)
        with self.assertRaises(ProtocolFault) as ctx:
            parse_control_envelope(doc, now=self.now)
        self.assertEqual(ctx.exception.error.code, "PROTOCOL_INCOMPATIBLE")
        self.assertEqual(ctx.exception.error.category, "incompatible")

    def test_expired_message_rejected(self):
        doc = dict(self.base, expires_at=(self.now - timedelta(milliseconds=1)).isoformat())
        with self.assertRaises(ProtocolFault) as ctx:
            parse_control_envelope(doc, now=self.now)
        self.assertEqual(ctx.exception.error.code, "DEADLINE_EXCEEDED")
        self.assertTrue(ctx.exception.error.retryable)

    def test_future_issued_at_beyond_skew_rejected(self):
        doc = dict(
            self.base,
            issued_at=(self.now + timedelta(seconds=31)).isoformat(),
            expires_at=(self.now + timedelta(seconds=60)).isoformat(),
        )
        with self.assertRaises(ProtocolFault) as ctx:
            parse_control_envelope(doc, now=self.now)
        self.assertEqual(ctx.exception.error.code, "CLOCK_SKEW")

    def test_unknown_field_rejected(self):
        doc = dict(self.base, shell_command="whoami")
        with self.assertRaises(ProtocolFault) as ctx:
            parse_control_envelope(doc, now=self.now)
        self.assertEqual(ctx.exception.error.code, "INVALID_ARGUMENT")

    def test_missing_field_rejected(self):
        doc = dict(self.base)
        del doc["actor_id"]
        with self.assertRaises(ProtocolFault):
            parse_control_envelope(doc, now=self.now)

    def test_structured_error_serializes(self):
        doc = dict(self.base, protocol_major=7)
        try:
            parse_control_envelope(doc, now=self.now)
        except ProtocolFault as exc:
            out = exc.error.to_dict()
        self.assertEqual(out["request_id"], "req-1")
        self.assertIn("supported_major", out["details"])
        self.assertFalse(out["retryable"])


if __name__ == "__main__":
    unittest.main()
