"""Gateway must fail closed if the fleet suspension registry is unavailable."""

import sqlite3
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from services.gateway.auth import AuthResult, GatewayAuthManager


@pytest.fixture
def guard() -> GatewayAuthManager:
    manager = GatewayAuthManager.__new__(GatewayAuthManager)
    manager.owner_account_store = None
    return manager


def test_fleet_ban_rejects_registered_account(guard: GatewayAuthManager) -> None:
    registry = Mock()
    registry.is_fleet_banned.return_value = True
    registry.get_fleet_ban_info.return_value = {"reason": "suspended by operator"}
    with patch("services.portal.passkey_routes.FLEET_ACCOUNT_STORE", registry):
        result = guard._guard_auth_result(AuthResult(account_id="provider-a"))
    assert result.status_code == HTTPStatus.FORBIDDEN
    assert not result.is_authenticated


@pytest.mark.parametrize(
    "error",
    [
        sqlite3.OperationalError("database is locked"),
        OSError("database inaccessible"),
        RuntimeError("fleet registry unavailable"),
        ValueError("malformed ban response"),
    ],
)
def test_failed_ban_lookup_never_authorizes_fleet(
    guard: GatewayAuthManager, error: Exception,
) -> None:
    registry = Mock()
    registry.is_fleet_banned.side_effect = error
    with patch("services.portal.passkey_routes.FLEET_ACCOUNT_STORE", registry):
        result = guard._guard_auth_result(AuthResult(account_id="provider-a"))
    assert result.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert result.account_id is None
    assert result.is_authenticated is False
    assert "cannot be verified" in result.error_message


def test_known_unbanned_account_still_authorized(guard: GatewayAuthManager) -> None:
    registry = Mock()
    registry.is_fleet_banned.return_value = False
    with patch("services.portal.passkey_routes.FLEET_ACCOUNT_STORE", registry):
        result = guard._guard_auth_result(AuthResult(account_id="provider-a"))
    assert result.is_authenticated
    assert result.status_code == HTTPStatus.OK


def test_admin_path_does_not_query_fleet_registry(guard: GatewayAuthManager) -> None:
    with patch("services.portal.passkey_routes.FLEET_ACCOUNT_STORE") as registry:
        result = guard._guard_auth_result(AuthResult(account_id="admin_root"))
    assert result.is_authenticated
    registry.is_fleet_banned.assert_not_called()
