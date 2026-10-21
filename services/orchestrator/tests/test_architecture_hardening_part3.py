"""Unit tests for Architecture Hardening Part 3."""
from __future__ import annotations

import unittest

from services.orchestrator.architecture_hardening_part3 import (
    RuntimeSandbox,
    HardConstraintScheduler,
    AuditableBillingEventLogger,
    ArbitraryCodeExecutionError,
    HardConstraintViolationError,
    BillingAuditError
)

class TestRuntimeSandbox(unittest.TestCase):
    def setUp(self):
        self.sandbox = RuntimeSandbox(
            allowed_binaries={"llama.cpp", "onnxruntime"},
            allowed_model_formats={"gguf", "onnx"}
        )

    def test_valid_execution_request(self):
        result = self.sandbox.validate_execution_request(
            binary_name="llama.cpp",
            model_format="gguf",
            parameters={"threads": 4, "temperature": "0.7"}
        )
        self.assertTrue(result)

    def test_unauthorized_binary(self):
        with self.assertRaisesRegex(ArbitraryCodeExecutionError, "Binary 'bash' is not in the trusted whitelist"):
            self.sandbox.validate_execution_request("bash", "gguf", {})

    def test_unauthorized_model_format(self):
        with self.assertRaisesRegex(ArbitraryCodeExecutionError, "Model format 'pt' is not supported/trusted"):
            self.sandbox.validate_execution_request("llama.cpp", "pt", {})

    def test_command_injection_attempt(self):
        with self.assertRaisesRegex(ArbitraryCodeExecutionError, "Potential command injection detected"):
            self.sandbox.validate_execution_request("llama.cpp", "gguf", {"prompt": "hello; rm -rf /"})


class TestHardConstraintScheduler(unittest.TestCase):
    def setUp(self):
        self.scheduler = HardConstraintScheduler()
        self.available_nodes = [
            {
                "node_id": "node_1",
                "supported_models": ["llama-2-7b"],
                "available_memory_bytes": 8_000_000_000,
                "architecture": "x86_64",
                "privacy_policies": ["PUBLIC", "CONFIDENTIAL"],
                "region": "eu-central-1"
            },
            {
                "node_id": "node_2",
                "supported_models": ["llama-2-7b", "mistral-7b"],
                "available_memory_bytes": 4_000_000_000,
                "architecture": "arm64",
                "privacy_policies": ["PUBLIC"],
                "region": "us-east-1"
            }
        ]

    def test_feasible_nodes_filtered_correctly(self):
        constraints = {
            "required_model": "llama-2-7b",
            "min_memory_bytes": 6_000_000_000,
            "required_architecture": "x86_64"
        }
        feasible_nodes = self.scheduler.filter_feasible_nodes(self.available_nodes, constraints)
        self.assertEqual(len(feasible_nodes), 1)
        self.assertEqual(feasible_nodes[0]["node_id"], "node_1")

    def test_no_feasible_nodes(self):
        constraints = {
            "required_model": "gpt-4", # Not supported by any
        }
        with self.assertRaisesRegex(HardConstraintViolationError, "No feasible nodes found after applying hard constraints."):
            self.scheduler.filter_feasible_nodes(self.available_nodes, constraints)

    def test_privacy_constraint(self):
        constraints = {"privacy_tier": "CONFIDENTIAL"}
        feasible_nodes = self.scheduler.filter_feasible_nodes(self.available_nodes, constraints)
        self.assertEqual(len(feasible_nodes), 1)
        self.assertEqual(feasible_nodes[0]["node_id"], "node_1")

    def test_region_constraint(self):
        constraints = {"allowed_regions": ["us-east-1"]}
        feasible_nodes = self.scheduler.filter_feasible_nodes(self.available_nodes, constraints)
        self.assertEqual(len(feasible_nodes), 1)
        self.assertEqual(feasible_nodes[0]["node_id"], "node_2")


class TestAuditableBillingEventLogger(unittest.TestCase):
    def setUp(self):
        self.logger = AuditableBillingEventLogger()

    def test_successful_billing_derivation(self):
        self.logger.log_auditable_event("job_1", "EXECUTION_START", "prov_1", "client_1", {}, "sig_start")
        self.logger.log_auditable_event("job_1", "EXECUTION_PROGRESS", "prov_1", "client_1", {"tokens_processed": 50}, "sig_prog1")
        self.logger.log_auditable_event("job_1", "EXECUTION_PROGRESS", "prov_1", "client_1", {"tokens_processed": 100}, "sig_prog2")
        self.logger.log_auditable_event("job_1", "EXECUTION_END", "prov_1", "client_1", {}, "sig_end")

        billing_statement = self.logger.derive_billing_from_events("job_1", "client_1")

        self.assertEqual(billing_statement["job_id"], "job_1")
        self.assertEqual(billing_statement["audited_tokens"], 150)
        self.assertEqual(billing_statement["event_count"], 4)
        self.assertTrue("receipt_hash" in billing_statement)

    def test_missing_signature(self):
        with self.assertRaisesRegex(BillingAuditError, "must include a cryptographic signature"):
            self.logger.log_auditable_event("job_1", "EXECUTION_START", "prov_1", "client_1", {}, "")

    def test_incomplete_execution_chain(self):
        # Missing EXECUTION_START
        self.logger.log_auditable_event("job_1", "EXECUTION_END", "prov_1", "client_1", {}, "sig_end")
        with self.assertRaisesRegex(BillingAuditError, "Incomplete execution chain"):
            self.logger.derive_billing_from_events("job_1", "client_1")

    def test_client_id_mismatch(self):
        self.logger.log_auditable_event("job_1", "EXECUTION_START", "prov_1", "client_1", {}, "sig_start")
        self.logger.log_auditable_event("job_1", "EXECUTION_END", "prov_1", "client_2", {}, "sig_end") # Mismatch
        with self.assertRaisesRegex(BillingAuditError, "Client ID mismatch in event chain"):
            self.logger.derive_billing_from_events("job_1", "client_1")

    def test_cannot_log_after_settled(self):
        self.logger.log_auditable_event("job_1", "EXECUTION_START", "prov_1", "client_1", {}, "sig_start")
        self.logger.log_auditable_event("job_1", "EXECUTION_END", "prov_1", "client_1", {}, "sig_end")
        self.logger.derive_billing_from_events("job_1", "client_1") # Settles the job

        with self.assertRaisesRegex(BillingAuditError, "Cannot log event for settled job"):
            self.logger.log_auditable_event("job_1", "EXECUTION_PROGRESS", "prov_1", "client_1", {}, "sig_prog")

if __name__ == '__main__':
    unittest.main()
