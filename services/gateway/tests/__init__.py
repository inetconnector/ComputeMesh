"""ComputeMesh Gateway Tests."""

import os

# Gateway contract tests intentionally use the deterministic fixture backend.
# Production remains fail-closed because this package is never imported there.
os.environ.setdefault("COMPUTEMESH_INFERENCE_BACKEND", "synthetic")
os.environ.setdefault("COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE", "1")
