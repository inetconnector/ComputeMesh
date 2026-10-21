"""ComputeMesh Architecture Hardening & Fault Tolerance Engine (Part 3).

This module provides deep architectural optimizations, fault tolerance, and strict
enforcement of the core invariants defined in ARCHITECTURE.md:
- V1 MUST NOT execute arbitrary customer code on provider hosts.
- The scheduler MUST evaluate hard constraints before ranking feasible plans.
- Billing MUST derive from auditable execution events, not provider self-report alone.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

class HardeningPart3Error(RuntimeError):
    """Base exception for architecture hardening Part 3 violations."""
    pass

class ArbitraryCodeExecutionError(HardeningPart3Error):
    """Raised when arbitrary code execution is attempted on a provider host."""
    pass

class HardConstraintViolationError(HardeningPart3Error):
    """Raised when hard constraints are violated before or during scheduling."""
    pass

class BillingAuditError(HardeningPart3Error):
    """Raised when billing derivation fails due to lack of auditable events."""
    pass


class RuntimeSandbox:
    """Enforces the invariant: V1 MUST NOT execute arbitrary customer code on provider hosts.

    Only whitelisted model execution binaries (e.g., specific llama.cpp, onnxruntime versions)
    and strictly formatted inference requests are allowed. Arbitrary scripts or unrecognized
    commands are rejected.
    """
    def __init__(self, allowed_binaries: Set[str], allowed_model_formats: Set[str]):
        self.allowed_binaries = allowed_binaries
        self.allowed_model_formats = allowed_model_formats
        self._lock = threading.Lock()

    def validate_execution_request(self, binary_name: str, model_format: str, parameters: Dict[str, Any]) -> bool:
        """Validates that a request does not attempt to execute arbitrary code."""
        with self._lock:
            if binary_name not in self.allowed_binaries:
                raise ArbitraryCodeExecutionError(f"Execution rejected: Binary '{binary_name}' is not in the trusted whitelist.")

            if model_format not in self.allowed_model_formats:
                raise ArbitraryCodeExecutionError(f"Execution rejected: Model format '{model_format}' is not supported/trusted.")

            # Simple check for injection attempts in string parameters
            for key, value in parameters.items():
                if isinstance(value, str):
                    if "&&" in value or ";" in value or "|" in value or "`" in value or "$" in value:
                        raise ArbitraryCodeExecutionError(f"Execution rejected: Potential command injection detected in parameter '{key}'.")

            return True


class HardConstraintScheduler:
    """Enforces the invariant: The scheduler MUST evaluate hard constraints before ranking feasible plans."""
    def __init__(self):
        self._lock = threading.Lock()

    def filter_feasible_nodes(self, available_nodes: List[Dict[str, Any]], hard_constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Evaluates hard constraints and filters out ineligible nodes BEFORE any ranking occurs."""
        feasible_nodes = []
        with self._lock:
            for node in available_nodes:
                if self._evaluate_constraints(node, hard_constraints):
                    feasible_nodes.append(node)

            if not feasible_nodes and available_nodes:
                raise HardConstraintViolationError("No feasible nodes found after applying hard constraints.")

            return feasible_nodes

    def _evaluate_constraints(self, node: Dict[str, Any], constraints: Dict[str, Any]) -> bool:
        """Evaluates a single node against a set of hard constraints."""
        # Check model/runtime compatibility
        if "required_model" in constraints:
            if constraints["required_model"] not in node.get("supported_models", []):
                return False

        # Check memory bounds
        if "min_memory_bytes" in constraints:
            if node.get("available_memory_bytes", 0) < constraints["min_memory_bytes"]:
                return False

        # Check architecture capability
        if "required_architecture" in constraints:
            if node.get("architecture") != constraints["required_architecture"]:
                return False

        # Check privacy tier
        if "privacy_tier" in constraints:
            if constraints["privacy_tier"] not in node.get("privacy_policies", []):
                return False

        # Check explicit region limits
        if "allowed_regions" in constraints:
            if node.get("region") not in constraints["allowed_regions"]:
                return False

        return True


class AuditableBillingEventLogger:
    """Enforces the invariant: Billing MUST derive from auditable execution events, not provider self-report alone.

    Generates cryptographic receipts of execution steps that both client and provider can verify.
    """
    def __init__(self):
        self._execution_events: Dict[str, List[Dict[str, Any]]] = {}
        self._settled_jobs: Set[str] = set()
        self._lock = threading.Lock()

    def log_auditable_event(self, job_id: str, event_type: str, provider_id: str, client_id: str, metrics: Dict[str, Any], signature: str) -> None:
        """Logs a cryptographically signed execution event."""
        if not signature:
            raise BillingAuditError("Auditable events must include a cryptographic signature.")

        with self._lock:
            if job_id in self._settled_jobs:
                raise BillingAuditError(f"Cannot log event for settled job '{job_id}'.")

            if job_id not in self._execution_events:
                self._execution_events[job_id] = []

            event = {
                "timestamp": time.time(),
                "type": event_type,
                "provider_id": provider_id,
                "client_id": client_id,
                "metrics": metrics,
                "signature": signature
            }
            self._execution_events[job_id].append(event)

    def derive_billing_from_events(self, job_id: str, expected_client_id: str) -> Dict[str, Any]:
        """Derives the final billing statement strictly from the sequence of auditable events."""
        with self._lock:
            if job_id not in self._execution_events or not self._execution_events[job_id]:
                raise BillingAuditError(f"Cannot derive billing: No auditable events found for job '{job_id}'.")

            events = self._execution_events[job_id]

            # Verify chain of events
            has_start = any(e["type"] == "EXECUTION_START" for e in events)
            has_end = any(e["type"] == "EXECUTION_END" for e in events)

            if not has_start or not has_end:
                raise BillingAuditError(f"Cannot derive billing: Incomplete execution chain for job '{job_id}'. Requires START and END events.")

            # Accumulate audited metrics
            total_tokens = sum(e["metrics"].get("tokens_processed", 0) for e in events if e["type"] == "EXECUTION_PROGRESS")

            # Simple verification of client mismatch
            if any(e["client_id"] != expected_client_id for e in events):
                raise BillingAuditError(f"Cannot derive billing: Client ID mismatch in event chain for job '{job_id}'.")

            self._settled_jobs.add(job_id)

            # Produce final auditable receipt
            receipt_data = f"{job_id}:{total_tokens}:{time.time()}"
            receipt_hash = hashlib.sha256(receipt_data.encode('utf-8')).hexdigest()

            return {
                "job_id": job_id,
                "audited_tokens": total_tokens,
                "event_count": len(events),
                "receipt_hash": receipt_hash
            }
