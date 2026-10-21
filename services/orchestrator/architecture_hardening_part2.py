"""ComputeMesh Architecture Hardening & Fault Tolerance Engine (Part 2).

This module provides deep architectural optimizations, fault tolerance, and strict
enforcement of the core invariants defined in ARCHITECTURE.md:
- Model artifacts MUST be immutable and content-addressed.
- Privacy policy MUST be an enforceable placement constraint.
- A provider node MUST be able to drain without accepting new work.
- Recovery MUST never silently continue from unverified or ambiguous state.
- Telemetry MUST avoid prompt/output content by default.
"""
from __future__ import annotations

import hashlib
import time
import threading
from typing import Any, Callable, TypeVar, Optional, Dict, List

T = TypeVar('T')

class HardeningPart2Error(RuntimeError):
    """Base exception for architecture hardening Part 2 violations."""
    pass

class NodeDrainingError(HardeningPart2Error):
    """Raised when a node that is draining attempts to accept new work."""
    pass

class StateRecoveryError(HardeningPart2Error):
    """Raised when recovery encounters unverified or ambiguous state."""
    pass

class PrivacyConstraintError(HardeningPart2Error):
    """Raised when a privacy policy placement constraint is violated."""
    pass

class ImmutableArtifactError(HardeningPart2Error):
    """Raised when model artifact immutability or content-addressing is violated."""
    pass


class NodeLifecycleManager:
    """Manages provider node lifecycle, specifically enforcing draining invariants.

    Invariant: A provider node MUST be able to drain without accepting new work.
    """
    def __init__(self):
        self._state = "ACTIVE"
        self._active_jobs = 0
        self._lock = threading.Lock()

    def start_drain(self) -> None:
        """Transitions the node to a draining state."""
        with self._lock:
            if self._active_jobs == 0:
                self._state = "OFFLINE"
            else:
                self._state = "DRAINING"

    def is_draining(self) -> bool:
        with self._lock:
            return self._state in ["DRAINING", "OFFLINE"]

    def admit_job(self) -> None:
        """Admits a job if the node is ACTIVE. Fails if DRAINING."""
        with self._lock:
            if self._state != "ACTIVE":
                raise NodeDrainingError("Cannot accept new work: Node is draining or offline.")
            self._active_jobs += 1

    def complete_job(self) -> None:
        """Marks a job as complete. If draining and jobs hit 0, transitions to OFFLINE."""
        with self._lock:
            if self._active_jobs > 0:
                self._active_jobs -= 1
            if self._state == "DRAINING" and self._active_jobs == 0:
                self._state = "OFFLINE"

    def get_state(self) -> str:
        with self._lock:
            return self._state


class StrictStateRecovery:
    """Enforces that recovery MUST never silently continue from unverified or ambiguous state."""
    def __init__(self):
        self._verified_checkpoints: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    def save_checkpoint(self, state_id: str, state_data: bytes) -> None:
        with self._lock:
            checksum = hashlib.sha256(state_data).digest()
            self._verified_checkpoints[state_id] = checksum

    def recover_state(self, state_id: str, state_data: bytes) -> bool:
        """Attempts to recover state. Fails loudly on ambiguous/unverified state."""
        with self._lock:
            if state_id not in self._verified_checkpoints:
                raise StateRecoveryError(f"Cannot recover: State ID {state_id} is unverified/unknown.")

            checksum = hashlib.sha256(state_data).digest()
            if checksum != self._verified_checkpoints[state_id]:
                raise StateRecoveryError(f"Cannot recover: State ID {state_id} checksum mismatch. State is corrupted or ambiguous.")

            return True


class PrivacyConstraintEvaluator:
    """Enforces privacy policy as a hard placement constraint.

    Invariant: Privacy policy MUST be an enforceable placement constraint.
    """
    def __init__(self):
        pass

    def evaluate_placement(self, provider_capabilities: List[str], required_privacy_policies: List[str]) -> bool:
        """Evaluates if a provider meets all required privacy policies."""
        provider_caps_set = set(provider_capabilities)
        for policy in required_privacy_policies:
            if policy not in provider_caps_set:
                raise PrivacyConstraintError(f"Placement rejected: Provider lacks required privacy policy '{policy}'.")
        return True


class ContentAddressedArtifactRegistry:
    """Enforces that model artifacts MUST be immutable and content-addressed."""
    def __init__(self):
        self._artifacts: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    def register_artifact(self, artifact_data: bytes) -> str:
        """Registers an artifact and returns its content-addressed hash (SHA-256)."""
        checksum = hashlib.sha256(artifact_data).hexdigest()
        with self._lock:
            if checksum not in self._artifacts:
                self._artifacts[checksum] = artifact_data
        return checksum

    def get_artifact(self, artifact_hash: str) -> bytes:
        """Retrieves an artifact by its hash. Ensures immutability."""
        with self._lock:
            if artifact_hash not in self._artifacts:
                raise ImmutableArtifactError(f"Artifact not found: {artifact_hash}")
            return self._artifacts[artifact_hash]

    def verify_artifact(self, artifact_hash: str, provided_data: bytes) -> bool:
        """Verifies provided data matches the content-addressed hash."""
        expected_hash = hashlib.sha256(provided_data).hexdigest()
        if expected_hash != artifact_hash:
             raise ImmutableArtifactError(f"Artifact integrity violation: expected {artifact_hash}, got {expected_hash}")
        return True


class PrivacyPreservingTelemetry:
    """Enforces that Telemetry MUST avoid prompt/output content by default."""
    def __init__(self):
        self._telemetry_log: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def record_event(self, event_type: str, duration_ms: float, metadata: Dict[str, Any], raw_prompt: Optional[str] = None, raw_output: Optional[str] = None) -> None:
        """Records a telemetry event while strictly stripping raw prompt/output content."""
        safe_metadata = dict(metadata)
        # Ensure we never leak prompt or output content into telemetry
        if "prompt" in safe_metadata:
            del safe_metadata["prompt"]
        if "output" in safe_metadata:
            del safe_metadata["output"]

        event = {
            "type": event_type,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
            "metadata": safe_metadata
        }

        # We intentionally ignore raw_prompt and raw_output parameters to enforce the invariant

        with self._lock:
            self._telemetry_log.append(event)

    def get_logs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._telemetry_log)
