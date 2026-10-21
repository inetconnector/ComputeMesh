"""ComputeMesh Architecture Hardening (Part 8)

Enforces invariants:
- "A model version must declare at least: canonical model ID/version; source and license metadata; architecture; tokenizer/config digests; supported runtimes; quantizations; partitionable boundaries; memory model; compatibility constraints; expected shard set; safety/privacy metadata where applicable."
- "A shard must declare: immutable digest; model version; byte size; tensor/layer/expert range; quantization; runtime compatibility; expected device memory; artifact signature metadata."
"""

from typing import Any, Dict


class HardeningPart8Error(RuntimeError):
    """Base exception for Part 8 invariant violations."""
    pass


class ModelManifestError(HardeningPart8Error):
    """Raised when a model manifest violates declaration invariants."""
    pass


class ShardManifestError(HardeningPart8Error):
    """Raised when a shard manifest violates declaration invariants."""
    pass


class ModelManifestEnforcer:
    """Enforces: A model version must declare at least: ..."""

    REQUIRED_KEYS = [
        "model_id",
        "model_version",
        "upstream",  # source metadata
        "license",
        "architecture",
        "tokenizer_digest",
        "config_digest",
        "runtime_compatibility",
        "quantizations",
        "partitioning", # partitionable boundaries
        "memory_model",
        "compatibility_constraints",
        "artifacts", # expected shard set
        "safety_metadata" # safety/privacy metadata
    ]

    @classmethod
    def enforce(cls, manifest: Dict[str, Any]) -> None:
        """Validates that a model manifest contains all mandatory architectural fields."""
        if not isinstance(manifest, dict):
            raise ModelManifestError("Manifest must be a dictionary.")

        missing_keys = [key for key in cls.REQUIRED_KEYS if key not in manifest]
        if missing_keys:
            raise ModelManifestError(
                f"Model manifest violates invariant. Missing required declarations: {', '.join(missing_keys)}"
            )

        # Check specific nested or typed requirements based on schema/architecture.md
        if not isinstance(manifest.get("upstream"), dict):
             raise ModelManifestError("Model manifest 'upstream' (source metadata) must be a dictionary.")
        if not isinstance(manifest.get("license"), dict):
             raise ModelManifestError("Model manifest 'license' metadata must be a dictionary.")
        if not isinstance(manifest.get("runtime_compatibility"), list) or not manifest.get("runtime_compatibility"):
             raise ModelManifestError("Model manifest 'runtime_compatibility' must be a non-empty list.")
        if not isinstance(manifest.get("quantizations"), list):
             raise ModelManifestError("Model manifest 'quantizations' must be a list.")
        if not isinstance(manifest.get("partitioning"), dict):
             raise ModelManifestError("Model manifest 'partitioning' (boundaries) must be a dictionary.")
        if not isinstance(manifest.get("artifacts"), list) or not manifest.get("artifacts"):
             raise ModelManifestError("Model manifest 'artifacts' (expected shard set) must be a non-empty list.")


class ShardManifestEnforcer:
    """Enforces: A shard must declare: ..."""

    REQUIRED_KEYS = [
        "digest", # immutable digest
        "model_version",
        "size_bytes", # byte size
        "range", # tensor/layer/expert range
        "quantization",
        "runtime_compatibility",
        "expected_device_memory",
        "signature_metadata" # artifact signature metadata
    ]

    @classmethod
    def enforce(cls, shard_manifest: Dict[str, Any]) -> None:
        """Validates that a shard manifest contains all mandatory architectural fields."""
        if not isinstance(shard_manifest, dict):
            raise ShardManifestError("Shard manifest must be a dictionary.")

        missing_keys = [key for key in cls.REQUIRED_KEYS if key not in shard_manifest]
        if missing_keys:
            raise ShardManifestError(
                f"Shard manifest violates invariant. Missing required declarations: {', '.join(missing_keys)}"
            )

        if not isinstance(shard_manifest.get("size_bytes"), int) or shard_manifest.get("size_bytes") <= 0:
            raise ShardManifestError("Shard manifest 'size_bytes' must be a positive integer.")
        if not isinstance(shard_manifest.get("expected_device_memory"), int) or shard_manifest.get("expected_device_memory") <= 0:
            raise ShardManifestError("Shard manifest 'expected_device_memory' must be a positive integer.")
        if not isinstance(shard_manifest.get("runtime_compatibility"), list) or not shard_manifest.get("runtime_compatibility"):
             raise ShardManifestError("Shard manifest 'runtime_compatibility' must be a non-empty list.")
        if not isinstance(shard_manifest.get("range"), dict):
             raise ShardManifestError("Shard manifest 'range' must be a dictionary.")
