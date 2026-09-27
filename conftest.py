"""Repository-wide pytest defaults for explicitly synthetic test serving."""
from __future__ import annotations

import os


os.environ.setdefault("COMPUTEMESH_ALLOW_STATIC_MODEL_CATALOG", "1")
