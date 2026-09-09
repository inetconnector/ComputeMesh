"""Point tkinter at the Tcl/Tk trees bundled into the frozen executable."""
from __future__ import annotations

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    os.environ.setdefault("TCL_LIBRARY", str(bundle_root / "_tcl_data"))
    os.environ.setdefault("TK_LIBRARY", str(bundle_root / "_tk_data"))
