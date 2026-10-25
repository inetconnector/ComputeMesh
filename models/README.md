# Model Metadata and Examples

**Status:** Implemented canonical model manifest fixtures and schemas.

## Purpose

Versioned model manifests, shard-layout metadata, compatibility notes, and test fixtures.

## Responsibilities

- canonical model manifests (`qwen2.5-0.5b-instruct.computemesh-model-manifest.json`)
- diffusion model support (`diffusion/`)
- supported-runtime and quantization metadata
- test fixtures and schema validation

## Implementation status

Canonical model manifests are implemented and validated against `model_manifest.schema.json` via `tools/benchmark/gguf_manifest.py` and subsystem tests. Large model weight files are stored externally in `COMPUTEMESH_MODEL_DIR` and verified against exact SHA-256 and size metadata before execution.

