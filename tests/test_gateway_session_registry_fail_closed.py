"""Gateway session/provider backend failures must never silently authorize teasers."""

from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from services.gateway.auth import GatewayAuthManager


@pytest.mark.parametrize(
    "failure",
    [OSError("session database unavailable"), RuntimeError("backend bug")],
)
def test_session_lookup_failure_blocks_teaser(failure: Exception) -> None:
    manager = GatewayAuthManager.__new__(GatewayAuthManager)
    manager._lookup_registered_key = Mock(return_value=None)
    with patch(
        "services.portal.passkey_routes.session_account_from_headers",
        side_effect=failure,
    ):
        outcome = manager.authenticate_request(
            {"Cookie": "cm_fleet_session=fixture-session"},
            client_address=("198.51.100.22", 12345),
            allow_teaser=True,
        )
    assert outcome.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert outcome.account_id is None
    assert outcome.is_teaser is False


def test_provider_ip_registry_failure_blocks_teaser() -> None:
    manager = GatewayAuthManager.__new__(GatewayAuthManager)
    manager._lookup_registered_key = Mock(return_value=None)
    with patch(
        "services.gateway.auth.resolve_client_ip",
        side_effect=OSError("provider registry not reachable"),
    ):
        outcome = manager.authenticate_request(
            {}, client_address=("198.51.100.22", 12345), allow_teaser=True,
        )
    assert outcome.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert outcome.is_teaser is False


def test_unexpected_gateway_programming_error_remains_visible() -> None:
    manager = GatewayAuthManager.__new__(GatewayAuthManager)
    manager._lookup_registered_key = Mock(return_value=None)
    with patch(
        "services.portal.passkey_routes.session_account_from_headers",
        side_effect=AssertionError("unexpected authentication bug"),
    ):
        with pytest.raises(AssertionError, match="unexpected authentication bug"):
            manager.authenticate_request({}, allow_teaser=True)
