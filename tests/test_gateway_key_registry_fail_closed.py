"""Gateway registry I/O errors must not become empty keys or anonymous teasers."""

from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from services.gateway.auth import (
    GatewayAuthManager,
    GatewayCredentialStoreError,
    _load_api_key_store,
)


def test_unreadable_configured_key_store_is_not_silently_empty(tmp_path: Path) -> None:
    store = tmp_path / "api-keys.json"
    store.write_text("{}", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=PermissionError("registry denied")), pytest.raises(GatewayCredentialStoreError, match="unreadable"):
        _load_api_key_store(store)


def test_missing_unconfigured_key_store_remains_empty(tmp_path: Path) -> None:
    assert _load_api_key_store(tmp_path / "missing.json") == {}
    assert _load_api_key_store(None) == {}


def test_unreadable_registry_cannot_downgrade_bearer_to_teaser() -> None:
    auth = GatewayAuthManager.__new__(GatewayAuthManager)
    auth._lookup_registered_key = Mock(
        side_effect=GatewayCredentialStoreError("registry unavailable")
    )
    response = auth.authenticate_request(
        {"Authorization": "Bearer cm_live_example_token"},
        client_address=("198.51.100.23", 12000),
        allow_teaser=True,
    )
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.account_id is None
    assert response.is_teaser is False
    assert not response.is_authenticated
