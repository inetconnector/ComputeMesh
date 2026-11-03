"""Unexpected crypto and network faults must not be silently disguised."""

from unittest.mock import patch

import pytest
from services.mcp.builtin import network_tools
from tools.security.ed25519_verify import verify_ed25519_signature


def test_invalid_ed25519_bytes_fail_closed() -> None:
    assert verify_ed25519_signature(b"invalid", b"message", b"invalid") is False


def test_crypto_implementation_bug_is_visible() -> None:
    with patch(
        "cryptography.hazmat.primitives.asymmetric.ed25519."
        "Ed25519PublicKey.from_public_bytes",
        side_effect=RuntimeError("unexpected cryptography fault"),
    ), pytest.raises(RuntimeError, match="unexpected cryptography fault"):
        verify_ed25519_signature(bytes(32), b"message", bytes(64))


def test_ssl_transport_error_stays_failed() -> None:
    with patch.object(
        network_tools, "resolve_public_host", side_effect=TimeoutError("TLS timeout"),
    ):
        result = network_tools._check_ssl("example.com")
    assert result["valid"] is False
    assert "TLS timeout" in result["error"]


def test_ssl_programming_error_not_disguised_as_certificate_failure() -> None:
    with patch.object(
        network_tools, "resolve_public_host", side_effect=RuntimeError("unexpected resolver bug"),
    ), pytest.raises(RuntimeError, match="unexpected resolver bug"):
        network_tools._check_ssl("example.com")


def test_http_expected_network_failure_returns_error() -> None:
    with (
        patch.object(network_tools, "validate_public_url"),
        patch.object(network_tools, "build_safe_public_opener") as build,
    ):
        build.return_value.open.side_effect = OSError("connection reset")
        result = network_tools._check_http("example.com")
    assert "connection reset" in result["http"]["error"]
    assert "connection reset" in result["https"]["error"]


def test_http_unexpected_programming_fault_propagates() -> None:
    with (
        patch.object(network_tools, "validate_public_url"),
        patch.object(network_tools, "build_safe_public_opener") as build,
    ):
        build.return_value.open.side_effect = RuntimeError("unexpected opener bug")
        with pytest.raises(RuntimeError, match="unexpected opener bug"):
            network_tools._check_http("example.com")
