"""ComputeMesh Architecture Hardening & Fault Tolerance Engine (Part 4).

This module provides deep architectural optimizations, fault tolerance, and strict
enforcement of the core invariants defined in ARCHITECTURE.md:
- The scheduler MUST model prefill and decode separately.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

class HardeningPart4Error(RuntimeError):
    """Base exception for architecture hardening Part 4 violations."""
    pass

class SplitPhaseModelingError(HardeningPart4Error):
    """Raised when the scheduler fails to model prefill and decode separately."""
    pass


class SplitPhasePerformanceModel:
    """Enforces the invariant: The scheduler MUST model prefill and decode separately.

    It separates prefill estimation and decode estimation logic, ensuring that
    a placement plan handles the different resource and latency profiles of both phases.
    """
    def __init__(self):
        self._lock = threading.Lock()

    def estimate_job_performance(self, node_profile: Dict[str, Any], prompt_tokens: int, expected_decode_tokens: int) -> Dict[str, Any]:
        """Estimates the performance of a job by explicitly modeling prefill and decode separately."""

        # We MUST ensure the caller provides tokens for both phases to prove they are modeled
        if prompt_tokens < 0 or expected_decode_tokens < 0:
            raise SplitPhaseModelingError("Prompt and decode tokens must be non-negative.")

        if "prefill_speed_tps" not in node_profile or "decode_speed_tps" not in node_profile:
            raise SplitPhaseModelingError("Node profile MUST provide separate 'prefill_speed_tps' and 'decode_speed_tps' metrics.")

        prefill_tps = node_profile["prefill_speed_tps"]
        decode_tps = node_profile["decode_speed_tps"]

        if prefill_tps <= 0 or decode_tps <= 0:
            raise SplitPhaseModelingError("Node profile TPS metrics must be strictly positive.")

        with self._lock:
            # Separately calculated latency profiles
            estimated_prefill_time_sec = prompt_tokens / prefill_tps
            estimated_decode_time_sec = expected_decode_tokens / decode_tps

            # Additional logic can be added here such as separate memory modelling for prefill (activation memory)
            # vs decode (KV cache growth)

            return {
                "estimated_prefill_time_sec": estimated_prefill_time_sec,
                "estimated_decode_time_sec": estimated_decode_time_sec,
                "total_estimated_time_sec": estimated_prefill_time_sec + estimated_decode_time_sec,
                "bottleneck": "prefill" if estimated_prefill_time_sec > estimated_decode_time_sec else "decode"
            }
