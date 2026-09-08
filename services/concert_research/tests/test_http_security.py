from __future__ import annotations

import unittest
from urllib import request

from services.concert_research.http_client import ValidatingRedirectHandler


class ConcertHttpSecurityTests(unittest.TestCase):
    def test_private_redirect_is_rejected_before_follow(self):
        handler = ValidatingRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(
                request.Request("https://example.com/start"),
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1/private",
            )

    def test_metadata_redirect_is_rejected_before_follow(self):
        handler = ValidatingRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(
                request.Request("https://example.com/start"),
                None,
                302,
                "Found",
                {},
                "http://169.254.169.254/latest/meta-data",
            )


if __name__ == "__main__":
    unittest.main()
