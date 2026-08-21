import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

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

    def test_benchmark_peer_identity_fields_are_optional_but_paired(self):
        validator = self.load("benchmark_result.schema.json")
        base = {
            "schema_version": 1,
            "run_id": "net-1",
            "benchmark_name": "tcp_network_path",
            "captured_at": "2026-08-21T20:00:00Z",
            "profile_revision": 3,
            "conditions": {"warm_state": "warm"},
            "metrics": {"rtt_ms_p50": 1.0},
            "raw_samples": [],
        }
        validator.validate(base)

        bound = json.loads(json.dumps(base))
        bound["conditions"].update({
            "local_node_id": "node-a",
            "peer_node_id": "node-b",
            "peer_identity_binding": "unauthenticated_server_report_v1",
        })
        validator.validate(bound)

        missing_binding = json.loads(json.dumps(base))
        missing_binding["conditions"]["peer_node_id"] = "node-b"
        with self.assertRaises(ValidationError):
            validator.validate(missing_binding)

    def test_model_manifest_accepts_optional_layer_count(self):
        validator = self.load("model_manifest.schema.json")
        document = {
            "schema_version": 1,
            "model_id": "m",
            "model_version": "1",
            "architecture": "test",
            "layer_count": 32,
            "license": {"id": "test", "source": "test"},
            "runtime_compatibility": [{"runtime": "llama.cpp"}],
            "quantizations": ["Q4_K_M"],
            "partitioning": {"allowed": ["contiguous_layers"]},
            "artifacts": [{"digest": "sha256:" + "a" * 64, "size_bytes": 1234}],
        }
        validator.validate(document)
        document["layer_count"] = 1
        with self.assertRaises(ValidationError):
            validator.validate(document)


if __name__ == "__main__":
    unittest.main()
