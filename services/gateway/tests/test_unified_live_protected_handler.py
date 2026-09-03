from __future__ import annotations

from http import HTTPStatus
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest

from services.gateway.live_handler import LiveGatewayHandler
from services.gateway.protected_transport_mixin import ProtectedTransportMixin
from services.gateway.unified_live_handler import build_unified_live_protected_handler


_ENV = (
    "COMPUTEMESH_UNIFIED_OWNER_CREDITS",
    "COMPUTEMESH_LEDGER_PATH",
    "COMPUTEMESH_OWNER_ACCOUNT_DB_PATH",
    "COMPUTEMESH_ACCOUNTING_DB_PATH",
    "COMPUTEMESH_INFERENCE_BACKEND",
    "COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE",
    "COMPUTEMESH_OWNER_PROMO_ONBOARDING",
    "STRIPE_API_KEY",
    "STRIPE_WEBHOOK_SECRET",
)


class UnifiedLiveProtectedHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = {name: os.environ.get(name) for name in _ENV}
        for name in _ENV:
            os.environ.pop(name, None)
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        os.environ["COMPUTEMESH_UNIFIED_OWNER_CREDITS"] = "1"
        os.environ["COMPUTEMESH_LEDGER_PATH"] = str(root / "ledger.jsonl")
        os.environ["COMPUTEMESH_OWNER_ACCOUNT_DB_PATH"] = str(root / "owners.sqlite3")
        os.environ["COMPUTEMESH_ACCOUNTING_DB_PATH"] = str(root / "accounting.sqlite3")
        os.environ["COMPUTEMESH_INFERENCE_BACKEND"] = "synthetic"
        os.environ["COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE"] = "1"

    def tearDown(self) -> None:
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    def test_composition_contains_one_owner_live_and_protected_chain(self) -> None:
        handler = build_unified_live_protected_handler()
        self.assertTrue(issubclass(handler, ProtectedTransportMixin))
        self.assertTrue(issubclass(handler, LiveGatewayHandler))
        names = [cls.__name__ for cls in handler.__mro__]
        self.assertLess(names.index("ProtectedTransportMixin"), names.index("LiveGatewayHandler"))
        self.assertIn("UnifiedOwnerGatewayHandler", names)
        self.assertIsNotNone(handler.owner_account_store)

    def test_legacy_public_confidential_alias_is_404_before_old_handler(self) -> None:
        handler_cls = build_unified_live_protected_handler()
        handler = object.__new__(handler_cls)
        handler.path = "/v1/confidential/chat/completions"
        handler.headers = {"Content-Length": "0"}
        handler.rfile = BytesIO(b"")
        errors = []
        handler._send_error_response = lambda message, kind, status: errors.append(  # type: ignore[method-assign]
            (message, kind, int(status))
        )
        handler.do_POST()
        self.assertEqual(errors, [("Not Found", "invalid_request_error", int(HTTPStatus.NOT_FOUND))])


if __name__ == "__main__":
    unittest.main()
