"""Passkey rate-limit source IP must not be spoofable by remote callers."""

from unittest.mock import patch

import pytest

from services.portal import passkey_routes as passkeys


@pytest.mark.parametrize(
    "forgery",
    [
        {"X-Forwarded-For": "198.51.100.7"},
        {"X-Real-IP": "198.51.100.8"},
        {"X-Forwarded-For": "198.51.100.7, 10.10.1.1"},
    ],
)
def test_untrusted_peer_cannot_select_rate_limit_ip(forgery: dict[str, str]) -> None:
    assert passkeys._client_ip(forgery, ("203.0.113.50", 12345)) == "203.0.113.50"


def test_known_loopback_proxy_can_report_valid_client_ip() -> None:
    headers = {"X-Forwarded-For": "198.51.100.1, 127.0.0.1"}
    assert passkeys._client_ip(headers, ("127.0.0.1", 8080)) == "198.51.100.1"


def test_explicitly_configured_trusted_proxy_can_report_client_ip() -> None:
    with patch.dict("os.environ", {"COMPUTEMESH_TRUSTED_PROXY_IPS": "10.24.0.7"}):
        assert passkeys._client_ip(
            {"X-Real-IP": "2001:db8::3"}, ("10.24.0.7", 8000)
        ) == "2001:db8::3"


@pytest.mark.parametrize(
    "invalid",
    ["not-an-ip", "198.51.100.77.evil", "198.51.100.3:8080", "unknown"],
)
def test_invalid_forwarded_values_are_not_accepted(invalid: str) -> None:
    assert passkeys._client_ip(
        {"X-Forwarded-For": invalid}, ("127.0.0.1", 8000)
    ) == "127.0.0.1"


def test_missing_transport_peer_uses_local_default_without_header_auth() -> None:
    assert passkeys._client_ip(
        {"X-Forwarded-For": "203.0.113.99"}
    ) == "127.0.0.1"
