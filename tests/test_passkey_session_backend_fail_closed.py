"""Fleet session lookup outages must never become anonymous access."""

from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest
from services.gateway.auth import GatewayAuthManager
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStoreError


@pytest.mark.parametrize("failure", [
    OSError("database inaccessible"),
    FleetAccountStoreError("session storage offline"),
])
def test_real_fleet_session_outage_propagates(failure: Exception) -> None:
    store = Mock()
    store.get_session_account.side_effect = failure
    with patch.object(passkey_routes, "FLEET_ACCOUNT_STORE", store), pytest.raises((OSError, FleetAccountStoreError)):
        passkey_routes.session_account_from_headers(
            {"Cookie": "cm_fleet_session=test-cookie"}
        )


def test_real_fleet_outage_is_unauthed_gateway_503() -> None:
    manager = GatewayAuthManager.__new__(GatewayAuthManager)
    manager._lookup_registered_key = Mock(return_value=None)
    store = Mock()
    store.get_session_account.side_effect = OSError("session database unavailable")
    with patch.object(passkey_routes, "FLEET_ACCOUNT_STORE", store):
        result = manager.authenticate_request(
            {"Cookie": "cm_fleet_session=test-cookie"},
            client_address=("198.51.100.50", 8080), allow_teaser=True,
        )
    assert result.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert not result.is_authenticated
    assert not result.is_teaser


def test_unknown_session_is_not_a_database_outage() -> None:
    store = Mock()
    store.get_session_account.return_value = None
    with patch.object(passkey_routes, "FLEET_ACCOUNT_STORE", store):
        assert passkey_routes.session_account_from_headers(
            {"Cookie": "cm_fleet_session=expired-session"}
        ) is None


def test_failed_owner_key_provisioning_is_visible() -> None:
    store = Mock()
    store.get_account_by_owner_key.return_value = None
    store._connection.side_effect = OSError("cannot connect to fleet database")
    with patch.object(passkey_routes, "FLEET_ACCOUNT_STORE", store), pytest.raises(FleetAccountStoreError, match="provisioning unavailable"):
        passkey_routes.session_account_from_headers(
            {"X-Owner-Key": "inet-test-owner"}
        )
