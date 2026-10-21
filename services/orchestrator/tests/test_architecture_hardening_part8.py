"""Tests for Architecture Hardening Part 8 (Manifest Invariants)"""
import pytest
from services.orchestrator.architecture_hardening_part8 import (
    ModelManifestEnforcer,
    ShardManifestEnforcer,
    ModelManifestError,
    ShardManifestError
)


def test_model_manifest_valid():
    """Test that a valid model manifest passes enforcement."""
    valid_manifest = {
        "model_id": "test-model-v1",
        "model_version": "1.0",
        "upstream": {"publisher": "Acme", "model_name": "Test", "source": "local"},
        "license": {"id": "MIT", "source": "local"},
        "architecture": "llama",
        "tokenizer_digest": "sha256:123",
        "config_digest": "sha256:456",
        "runtime_compatibility": [{"runtime": "llama.cpp"}],
        "quantizations": ["Q4_K_M"],
        "partitioning": {"allowed": ["contiguous_layers"]},
        "memory_model": "unified",
        "compatibility_constraints": {},
        "artifacts": [{"digest": "sha256:789", "size_bytes": 1000}],
        "safety_metadata": {"compliant": True}
    }
    # Should not raise
    ModelManifestEnforcer.enforce(valid_manifest)


def test_model_manifest_missing_keys():
    """Test that a model manifest missing keys raises an error."""
    invalid_manifest = {
        "model_id": "test-model-v1",
        "model_version": "1.0",
        "upstream": {"publisher": "Acme", "model_name": "Test", "source": "local"},
        # missing license, architecture, etc.
    }
    with pytest.raises(ModelManifestError) as exc:
        ModelManifestEnforcer.enforce(invalid_manifest)
    assert "Missing required declarations" in str(exc.value)


def test_model_manifest_invalid_types():
    """Test that a model manifest with invalid types raises an error."""
    invalid_manifest = {
        "model_id": "test-model-v1",
        "model_version": "1.0",
        "upstream": "not_a_dict",  # Should be a dict
        "license": {"id": "MIT", "source": "local"},
        "architecture": "llama",
        "tokenizer_digest": "sha256:123",
        "config_digest": "sha256:456",
        "runtime_compatibility": [{"runtime": "llama.cpp"}],
        "quantizations": ["Q4_K_M"],
        "partitioning": {"allowed": ["contiguous_layers"]},
        "memory_model": "unified",
        "compatibility_constraints": {},
        "artifacts": [{"digest": "sha256:789", "size_bytes": 1000}],
        "safety_metadata": {"compliant": True}
    }
    with pytest.raises(ModelManifestError) as exc:
        ModelManifestEnforcer.enforce(invalid_manifest)
    assert "must be a dictionary" in str(exc.value)


def test_shard_manifest_valid():
    """Test that a valid shard manifest passes enforcement."""
    valid_shard = {
        "digest": "sha256:abc",
        "model_version": "1.0",
        "size_bytes": 1048576,
        "range": {"start_layer": 0, "end_layer": 10},
        "quantization": "Q4_K_M",
        "runtime_compatibility": [{"runtime": "llama.cpp"}],
        "expected_device_memory": 2048576,
        "signature_metadata": {"signer": "mesh-auth"}
    }
    # Should not raise
    ShardManifestEnforcer.enforce(valid_shard)


def test_shard_manifest_missing_keys():
    """Test that a shard manifest missing keys raises an error."""
    invalid_shard = {
        "digest": "sha256:abc",
        "model_version": "1.0",
        "size_bytes": 1048576,
        # missing range, quantization, etc.
    }
    with pytest.raises(ShardManifestError) as exc:
        ShardManifestEnforcer.enforce(invalid_shard)
    assert "Missing required declarations" in str(exc.value)


def test_shard_manifest_invalid_types():
    """Test that a shard manifest with invalid types raises an error."""
    invalid_shard = {
        "digest": "sha256:abc",
        "model_version": "1.0",
        "size_bytes": -100,  # Invalid size
        "range": {"start_layer": 0, "end_layer": 10},
        "quantization": "Q4_K_M",
        "runtime_compatibility": [{"runtime": "llama.cpp"}],
        "expected_device_memory": 2048576,
        "signature_metadata": {"signer": "mesh-auth"}
    }
    with pytest.raises(ShardManifestError) as exc:
        ShardManifestEnforcer.enforce(invalid_shard)
    assert "must be a positive integer" in str(exc.value)
