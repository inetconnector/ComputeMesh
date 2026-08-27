"""Compliance wrapper around the preserved ComputeMesh portal server core.

The pre-hardening implementation is retained verbatim in server_core.py so existing
routes/tests remain available. This wrapper adds only the additional first-party
portal-core.js route required by the compliance UI wrapper.
"""
from __future__ import annotations

from http import HTTPStatus
import sys

from services.portal import server_core as _core

# Re-export the complete historical module surface, including private helpers used by
# regression tests and operator tooling.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


class PortalHandler(_core.PortalHandler):
    """Core portal handler plus first-party compliance assets."""

    def do_GET(self) -> None:
        clean_path = self.path.split("?", 1)[0].rstrip("/")
        if clean_path == "/portal-core.js":
            if not self._check_rate_limit():
                return
            target = _core._safe_resolve_portal_file("portal-core.js")
            if target is None:
                self._send_json({"error": "Resource Not Found"}, HTTPStatus.NOT_FOUND)
                return
            self._send_bytes(target.read_bytes(), "application/javascript; charset=utf-8")
            return
        super().do_GET()


# Core functions (including main()) resolve their module-global PortalHandler. Point
# them at the hardened subclass without copying or deleting existing implementation.
_core.PortalHandler = PortalHandler


def main(argv: list[str] | None = None) -> int:
    return _core.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
