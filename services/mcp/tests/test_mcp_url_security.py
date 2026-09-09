# SPDX-License-Identifier: Apache-2.0
"""Regression tests for MCP public-network SSRF protections."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock, patch

from services.mcp.builtin.network_tools import _check_dns, _is_ip_blocked
from services.mcp.builtin.url_security import (
    SafePublicRedirectHandler,
    UnsafeTargetError,
    resolve_public_host,
    validate_public_url,
)
from services.mcp.builtin.web_fetch import execute_web_fetch


class TestPublicURLSecurity(unittest.TestCase):
    def test_private_and_special_ip_ranges_are_blocked(self):
        blocked = [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "::1",
            "fd00::1",
            "fe80::1",
        ]
        for address in blocked:
            with self.subTest(address=address):
                self.assertTrue(_is_ip_blocked(address))
        self.assertFalse(_is_ip_blocked("8.8.8.8"))
        self.assertFalse(_is_ip_blocked("1.1.1.1"))
        self.assertFalse(_is_ip_blocked("2606:4700:4700::1111"))

    def test_direct_private_url_is_rejected_without_dns(self):
        with patch("socket.getaddrinfo") as getaddrinfo:
            with self.assertRaises(UnsafeTargetError):
                validate_public_url("http://10.0.0.7/admin")
            getaddrinfo.assert_not_called()

    def test_url_credentials_and_internal_suffix_are_rejected(self):
        with self.assertRaises(UnsafeTargetError):
            validate_public_url("https://user:pass@example.com/")
        with self.assertRaises(UnsafeTargetError):
            validate_public_url("https://service.cluster.local/api")

    @patch("socket.getaddrinfo")
    def test_dns_answer_with_any_private_address_fails_closed(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443)),
        ]
        with self.assertRaisesRegex(UnsafeTargetError, "nicht-öffentliche IP"):
            resolve_public_host("example.com", 443)

    @patch("socket.getaddrinfo")
    def test_public_dns_answer_is_accepted(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]
        resolved = validate_public_url("https://example.com/path")
        self.assertEqual(resolved.addresses, ("93.184.216.34",))

    def test_redirect_to_private_target_is_blocked_before_follow(self):
        handler = SafePublicRedirectHandler()
        request = MagicMock()
        request.full_url = "https://example.com/start"
        with self.assertRaises(UnsafeTargetError):
            handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1/admin")

    @patch("services.mcp.builtin.web_fetch.build_safe_public_opener")
    def test_web_fetch_private_target_never_opens_socket(self, build_opener):
        result = execute_web_fetch("http://192.168.1.10/config")
        self.assertIn("Sicherheitsrichtlinie", result["error"])
        build_opener.assert_not_called()

    @patch("socket.getaddrinfo")
    def test_network_dns_uses_same_fail_closed_policy(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]
        result = _check_dns("evil.example")
        self.assertIn("error", result)
        self.assertIn("nicht-öffentliche IP", result["error"])


if __name__ == "__main__":
    unittest.main()
