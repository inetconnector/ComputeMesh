"""Gateway forwarded-IP trust must be bound to the transport proxy."""

import pytest
from services.gateway.auth import resolve_client_ip


@pytest.mark.parametrize(
    "header",
    [
        {"X-Forwarded-For": "198.51.100.7"},
        {"X-Real-IP": "198.51.100.7"},
        {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"},
    ],
)
def test_remote_caller_cannot_spoof_ip(header: dict[str, str]) -> None:
    assert resolve_client_ip(header, ("203.0.113.101", 5000)) == "203.0.113.101"


def test_missing_socket_identity_cannot_authorize_forwarded_header() -> None:
    assert resolve_client_ip({"X-Forwarded-For": "198.51.100.7"}) == "127.0.0.1"


@pytest.mark.parametrize("header", [
    "not-an-ip", "198.51.100.77.evil", "198.51.100.7:9999",
])
def test_invalid_proxy_claim_is_not_rate_limit_identity(header: str) -> None:
    assert resolve_client_ip(
        {"X-Forwarded-For": header}, ("127.0.0.1", 8080)
    ) == "127.0.0.1"


def test_explicit_trusted_proxy_is_required() -> None:
    headers = {"X-Forwarded-For": "198.51.100.7"}
    assert resolve_client_ip(headers, ("10.12.0.3", 8090)) == "10.12.0.3"
    assert resolve_client_ip(
        headers, ("10.12.0.3", 8090), trusted_proxies={"10.12.0.3"}
    ) == "198.51.100.7"


def test_loopback_prefix_is_not_automatically_authorized() -> None:
    assert resolve_client_ip(
        {"X-Forwarded-For": "198.51.100.7"}, ("127.40.3.1", 8080)
    ) == "127.40.3.1"
