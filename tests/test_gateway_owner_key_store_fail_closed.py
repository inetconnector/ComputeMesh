"""Owner-key authorization must not downgrade registry failures to teaser access."""

import sqlite3
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from services.gateway.auth import GatewayAuthManager


@pytest.mark.parametrize(
    "failure",
    [
        sqlite3.OperationalError("fleet database locked"),
        OSError("fleet database inaccessible"),
        RuntimeError("fleet store unavailable"),
        ValueError("owner record corrupt"),
    ],
)
def test_owner_key_registry_failure_returns_unauthed_503(failure: Exception) -> None:
    manager = GatewayAuthManager.__new__(GatewayAuthManager)
    manager._lookup_registered_key = Mock(return_value=None)
    registry = Mock()
    registry.resolve_latest_owner_key.side_effect = failure
    with patch("services.portal.passkey_routes.FLEET_ACCOUNT_STORE", registry):
        result = manager.authenticate_request(
            {"Authorization": "Bearer inet-fixture-owner-key"}, allow_teaser=True,
        )
    assert result.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert not result.is_authenticated
    assert result.account_id is None
    assert result.is_teaser is False
    assert "authorization temporarily unavailable" in result.error_message
    registry.get_account_by_owner_key.assert_not_called()


def test_owner_key_import_failure_does_not_grant_teaser() -> None:
    manager = GatewayAuthManager.__new__(GatewayAuthManager)
    manager._lookup_registered_key = Mock(return_value=None)
    registry = Mock()
    registry.resolve_latest_owner_key.side_effect = ImportError("backend unavailable")
    with patch("services.portal.passkey_routes.FLEET_ACCOUNT_STORE", registry):
        result = manager.authenticate_request(
            {"Authorization": "Bearer inet-fixture-owner-key"}, allow_teaser=True,
        )
    assert result.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert not result.is_authenticated
