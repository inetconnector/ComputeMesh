"""ComputeMesh Dashboard HTML Template Loader."""
from __future__ import annotations

import sys
from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def get_dashboard_html(auth_token: str | None = None) -> str:
    content = ""
    # 1. Look in standard static directory
    html_path = _STATIC_DIR / "index.html"
    if html_path.exists():
        try:
            content = html_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _ = exc

    # 2. Look in PyInstaller bundle directory (_MEIPASS)
    if not content and hasattr(sys, "_MEIPASS"):
        meipass_path = Path(sys._MEIPASS) / "services" / "appliance_dashboard" / "static" / "index.html"
        if meipass_path.exists():
            try:
                content = meipass_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                _ = exc

    # 3. Fallback placeholder
    if not content:
        content = """<!DOCTYPE html><html><head><title>ComputeMesh</title></head><body><h1>ComputeMesh Appliance Dashboard</h1></body></html>"""

    if auth_token:
        escaped_token = auth_token.replace("\\", "\\\\").replace('"', '\\"')
        injection = f'<script>window.__CM_NODE_AUTH_TOKEN__ = "{escaped_token}";</script>'
        if "</head>" in content:
            content = content.replace("</head>", f"{injection}\n</head>", 1)
        else:
            content = f"{injection}\n{content}"

    return content
