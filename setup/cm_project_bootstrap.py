"""Resolve repository-root package imports for supported direct Python entrypoints.

Importing this module before other ComputeMesh packages preserves file-path
entrypoint compatibility without placing imports below executable bootstrap
statements in the entrypoint implementation itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
