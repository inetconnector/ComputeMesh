import unittest

from protocol.session_contracts import (
    SessionMessageContractError,
    SessionMessageContractValidator,
)


class SessionMessageContractTests(unittest.TestCase):
    def setUp(self):
        self.validator = SessionMessageContractValidator()

    def test_exact_documented_session_message_set(self):
        self.assertEqual(
            self.validator.supported_messages(),
            frozenset(
                {
                    "NodeHello",
                    "NodeAuthenticate",
                    "CapabilityNegotiation",
                    "NodeProfileUpdate",
                    "BenchmarkReport",
                    "DrainRequest",
                }
            ),
        )

    def test_node_hello_is_strict_and_bounded(self):
        payload = {
            "protocol_major": 0,
            "protocol_minor": 2,
            "agent_version": "0.0.1",
            "platform": "windows-amd64",
            "supported_auth_methods": ["test-proof"],
            "capabilities": ["profile_v1"],
        }
        self.validator.validate("NodeHello", payload)
        with self.assertRaises(SessionMessageContractError):
            self.validator.validate("NodeHello", {**payload, "extra": True})

    def test_node_authenticate_requires_opaque_bounded_credential(self):
        self.validator.validate(
            "NodeAuthenticate",
            {"method": "test-proof", "credential": "proof"},
        )
        with self.assertRaises(SessionMessageContractError):
            self.validator.validate(
                "NodeAuthenticate",
                {"method": "test-proof", "credential": ""},
            )

    def test_profile_update_reuses_full_node_profile_contract(self):
        profile = {
            "schema_version": 1,
            "node_id": "node-1",
            "profile_revision": 7,
            "captured_at": "2026-08-21T12:00:00Z",
            "platform": {"os": "Linux", "release": "6.12", "architecture": "x86_64"},
            "cpu": {"logical_cores": 4},
            "memory": {"total_bytes": 1024, "available_bytes": 512},
            "devices": [],
            "runtime_capabilities": [],
            "provider_limits": {"draining": False},
            "benchmark_refs": [],
        }
        self.validator.validate("NodeProfileUpdate", profile)
        with self.assertRaises(SessionMessageContractError):
            broken = dict(profile)
            broken.pop("memory")
            self.validator.validate("NodeProfileUpdate", broken)

    def test_benchmark_report_reuses_benchmark_result_contract(self):
        report = {
            "schema_version": 1,
            "run_id": "run-1",
            "benchmark_name": "llama_cpp_decode",
            "captured_at": "2026-08-21T12:01:00Z",
            "profile_revision": 7,
            "conditions": {"warm_state": "warm"},
            "metrics": {"tokens_per_second": 10.0},
            "raw_samples": [10.0],
        }
        self.validator.validate("BenchmarkReport", report)
        with self.assertRaises(SessionMessageContractError):
            broken = dict(report)
            broken["metrics"] = {}
            self.validator.validate("BenchmarkReport", broken)

    def test_unknown_session_message_is_not_silently_accepted(self):
        with self.assertRaises(KeyError):
            self.validator.validate("JobAssignment", {})


if __name__ == "__main__":
    unittest.main()
