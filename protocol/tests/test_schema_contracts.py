import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

REPO = Path(__file__).resolve().parents[2]
SCHEMAS = REPO / "protocol" / "schemas"


class ProtocolSchemaTests(unittest.TestCase):
    def load(self, name):
        schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def test_control_envelope_schema(self):
        now = datetime.now(timezone.utc)
        document = {
            "protocol_major": 0,
            "protocol_minor": 2,
            "message_type": "CancelJob",
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "actor_id": "service-1",
            "target_id": "job-1",
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=30)).isoformat(),
            "expected_revision": 0,
            "payload": {},
        }
        self.load("control_envelope.schema.json").validate(document)

    def test_error_schema(self):
        document = {
            "code": "PROTOCOL_INCOMPATIBLE",
            "category": "incompatible",
            "retryable": False,
            "message": "unsupported protocol major",
            "details": {"supported_major": 0},
            "request_id": "req-1",
        }
        self.load("error.schema.json").validate(document)


if __name__ == "__main__":
    unittest.main()
