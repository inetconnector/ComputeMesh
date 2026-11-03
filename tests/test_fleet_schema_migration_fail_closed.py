"""SQLite fleet migrations may suppress only confirmed duplicate columns."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest
from services.portal.fleet_accounts import (
    FleetAccountStore,
    _add_fleet_column_idempotent,
)


def test_initialization_repeated_keeps_auth_and_passkey_data(tmp_path: Path) -> None:
    path = tmp_path / "fleet.db"
    store = FleetAccountStore(path)
    account = store.create_account("schema-test@example.invalid")
    store.add_passkey(account.account_id, "cred-schema", "pub", 0, "internal")

    again = FleetAccountStore(path)
    assert again.get_passkey("cred-schema").account_id == account.account_id
    with sqlite3.connect(path) as conn:
        assert "scope" in {r[1] for r in conn.execute("PRAGMA table_info(fleet_enrollment_tokens)")}
        columns = {r[1] for r in conn.execute("PRAGMA table_info(fleet_passkeys)")}
        assert {"nickname", "last_used_at"} <= columns


@pytest.mark.parametrize(
    "db_error",
    [
        "database is locked",
        "no such table: fleet_passkeys",
        "database disk image is malformed",
        "attempt to write a readonly database",
    ],
)
def test_unexpected_migration_database_errors_propagate(db_error: str) -> None:
    conn = Mock()
    conn.execute.side_effect = sqlite3.OperationalError(db_error)
    with pytest.raises(sqlite3.OperationalError, match=db_error):
        _add_fleet_column_idempotent(
            conn, "fleet_passkeys", "nickname",
            "ALTER TABLE fleet_passkeys ADD COLUMN nickname TEXT NOT NULL DEFAULT ''",
        )


def test_duplicate_column_requires_real_column_in_actual_sqlite() -> None:
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE fleet_passkeys (nickname TEXT NOT NULL DEFAULT '')")
        _add_fleet_column_idempotent(
            conn, "fleet_passkeys", "nickname",
            "ALTER TABLE fleet_passkeys ADD COLUMN nickname TEXT NOT NULL DEFAULT ''",
        )
        assert len(list(conn.execute("PRAGMA table_info(fleet_passkeys)"))) == 1


def test_fake_duplicate_error_does_not_hide_missing_column() -> None:
    conn = Mock()
    conn.execute.side_effect = sqlite3.OperationalError("duplicate column name: nickname")
    conn.execute.return_value = []
    # A duplicate exception without schema proof must not be accepted.
    conn.execute.side_effect = [
        sqlite3.OperationalError("duplicate column name: nickname"),
        [],
    ]
    with pytest.raises(sqlite3.OperationalError, match="duplicate column name"):
        _add_fleet_column_idempotent(
            conn, "fleet_passkeys", "nickname",
            "ALTER TABLE fleet_passkeys ADD COLUMN nickname TEXT NOT NULL DEFAULT ''",
        )


def test_duplicate_column_cannot_use_unapproved_table() -> None:
    conn = Mock()
    conn.execute.side_effect = sqlite3.OperationalError("duplicate column name: nickname")
    with pytest.raises(sqlite3.OperationalError, match="duplicate column name"):
        _add_fleet_column_idempotent(conn, "untrusted_table", "nickname", "ALTER TABLE untrusted_table ADD COLUMN nickname TEXT")
