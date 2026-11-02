"""Passkey fleet store initialization must never silently lose ban state."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStoreError


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("fleet store denied"),
        sqlite3.OperationalError("database is locked"),
        RuntimeError("filesystem unavailable"),
    ],
)
def test_authoritative_fleet_store_failure_does_not_create_tmp_db(
    tmp_path: Path, error: Exception,
) -> None:
    configured = tmp_path / "fleet.db"
    with (
        patch.object(passkey_routes, "_resolve_store_path", return_value=configured),
        patch.object(passkey_routes, "FleetAccountStore", side_effect=error) as construct,
    ):
        with pytest.raises(FleetAccountStoreError, match="authoritative fleet"):
            passkey_routes._build_store()
    construct.assert_called_once_with(configured)


def test_authoritative_fleet_store_success_uses_exact_path(tmp_path: Path) -> None:
    configured = tmp_path / "fleet.db"
    storage = Mock()
    with (
        patch.object(passkey_routes, "_resolve_store_path", return_value=configured),
        patch.object(passkey_routes, "FleetAccountStore", return_value=storage) as construct,
    ):
        result = passkey_routes._build_store()
    construct.assert_called_once_with(configured)
    assert result is storage
