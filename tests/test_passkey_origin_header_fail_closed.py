"""WebAuthn verification origins must never be trusted from request headers."""

from unittest.mock import patch

import pytest
from services.portal import passkey_routes as passkeys


@pytest.mark.parametrize(
    "forged_origin",
    [
        "https://evil.example",
        "https://mesh.inetconnector.com.evil.example",
        "https://not-authorized.example:8443",
        "http://localhost.evil.example:8000",
        "http://localhost:9999",
        "http://127.0.0.1:9999",
        "https://mesh.inetconnector.com@evil.example",
        "https://inetconnector.com:4443",
    ],
)
def test_request_origin_cannot_expand_passkey_trust(forged_origin: str) -> None:
    approved = passkeys._get_expected_origins()
    after = passkeys._get_expected_origins({"Origin": forged_origin})
    assert after == approved
    assert forged_origin not in after


def test_known_origins_remain_supported_without_reflection() -> None:
    origins = passkeys._get_expected_origins({"Origin": "https://mesh.inetconnector.com"})
    assert passkeys.EXPECTED_ORIGIN in origins
    assert "https://mesh.inetconnector.com" in origins
    assert "https://inetconnector.com" in origins
    assert len(origins) == len(set(origins))


def test_explicit_origin_setting_is_used_but_not_request_origin() -> None:
    with patch.object(passkeys, "EXPECTED_ORIGIN", "https://operator-allowed.example"):
        origins = passkeys._get_expected_origins({"Origin": "https://unapproved.example"})
    assert "https://operator-allowed.example" in origins
    assert "https://unapproved.example" not in origins
