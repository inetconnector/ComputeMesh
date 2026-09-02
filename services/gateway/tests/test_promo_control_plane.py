"""Tests for the fail-closed private promo control-plane HTTP client."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from services.gateway.promo_control_plane import (
    PromoControlPlaneClient,
    PromoControlPlaneError,
)


class _TestHandler(BaseHTTPRequestHandler):
    mode = "ok"
    last_path = ""
    last_auth = ""
    last_body: dict | None = None

    def do_POST(self) -> None:
        type(self).last_path = self.path
        type(self).last_auth = self.headers.get("Authorization", "")
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        type(self).last_body = json.loads(raw) if raw else {}
        if type(self).mode == "bad_request":
            payload = b'{"error":"invalid_promo_request"}'
            self.send_response(400)
        elif type(self).mode == "invalid_json":
            payload = b"not-json"
            self.send_response(200)
        else:
            payload = b'{"ok":true}'
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


class TestPromoControlPlaneClient(unittest.TestCase):
    def setUp(self) -> None:
        _TestHandler.mode = "ok"
        _TestHandler.last_path = ""
        _TestHandler.last_auth = ""
        _TestHandler.last_body = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.client = PromoControlPlaneClient(
            base_url=f"http://{host}:{port}",
            bearer_token="private-promo-token-123456789",
            timeout_seconds=2,
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_issue_challenge_posts_dedicated_bearer_and_json(self) -> None:
        result = self.client.issue_challenge({"hello": "world"})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(_TestHandler.last_path, "/internal/v1/promo/challenge")
        self.assertEqual(
            _TestHandler.last_auth,
            "Bearer private-promo-token-123456789",
        )
        self.assertEqual(_TestHandler.last_body, {"hello": "world"})

    def test_verify_uses_separate_private_path(self) -> None:
        result = self.client.verify_and_issue({"proof": {}})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(_TestHandler.last_path, "/internal/v1/promo/verify")

    def test_private_400_is_preserved_as_rejection(self) -> None:
        _TestHandler.mode = "bad_request"
        with self.assertRaises(PromoControlPlaneError) as ctx:
            self.client.issue_challenge({"bad": True})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_json_fails_closed(self) -> None:
        _TestHandler.mode = "invalid_json"
        with self.assertRaisesRegex(PromoControlPlaneError, "invalid JSON"):
            self.client.issue_challenge({"hello": "world"})

    def test_plaintext_transport_is_loopback_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback-only"):
            PromoControlPlaneClient(
                base_url="http://control-plane.example.invalid:8443",
                bearer_token="private-promo-token-123456789",
            )


if __name__ == "__main__":
    unittest.main()
