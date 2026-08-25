"""ComputeMesh Dashboard HTML Template Loader."""
from __future__ import annotations

import os
from pathlib import Path
import sys

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def get_dashboard_html() -> str:
    # 1. Look in standard static directory
    html_path = _STATIC_DIR / "index.html"
    if html_path.exists():
        try:
            return html_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # 2. Look in PyInstaller bundle directory (_MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        meipass_path = Path(sys._MEIPASS) / "services" / "appliance_dashboard" / "static" / "index.html"
        if meipass_path.exists():
            try:
                return meipass_path.read_text(encoding="utf-8")
            except Exception:
                pass

    # 3. Fallback placeholder
    return """<!DOCTYPE html><html><head><title>ComputeMesh</title></head><body><h1>ComputeMesh Appliance Dashboard</h1></body></html>"""
