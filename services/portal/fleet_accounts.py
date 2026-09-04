"""Durable portal login accounts for remote fleet administration.

Each account is authenticated by WebAuthn passkeys (no passwords) and owns a
generated fleet `owner_key` -- the same shared secret that nodes are already
configured with (tools/appliance/appliance_config.py, the dashboard's "Owner
Key" field) to bind themselves to a fleet in services/billing/owner_accounts.
This store only holds portal identity/session state; it never touches the
gateway's OwnerAccountStore directly.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import sqlite3

SCHEMA_VERSION = 1
CHALLENGE_TTL_MINUTES = 5
SESSION_TTL_DAYS = 30


class FleetAccountStoreError(Exception):
    """Raised when an account/passkey/session operation is invalid."""


@dataclass(frozen=True)
class FleetAccount:
    account_id: str
    email: str
    owner_key: str
    display_name: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class FleetPasskey:
    credential_id: str
    account_id: str
    public_key: str
    sign_count: int
    transports: str
    created_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise FleetAccountStoreError("a valid email address is required")
    return email


class FleetAccountStore:
    """SQLite-backed passkey accounts, credentials, sessions and login challenges."""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.storage_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_accounts (
                    account_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    owner_key TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_passkeys (
                    credential_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES fleet_accounts(account_id),
                    public_key TEXT NOT NULL,
                    sign_count INTEGER NOT NULL DEFAULT 0,
                    transports TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fleet_passkeys_account
                    ON fleet_passkeys(account_id);
                CREATE TABLE IF NOT EXISTS fleet_sessions (
                    session_token TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES fleet_accounts(account_id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_challenges (
                    email TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    challenge TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (email, kind)
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO fleet_schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # -- accounts ---------------------------------------------------------

    def create_account(self, email: str, *, display_name: str = "") -> FleetAccount:
        cleaned = _clean_email(email)
        account_id = "facc_" + secrets.token_hex(12)
        owner_key = "ok_" + secrets.token_urlsafe(24)
        now = utc_now()
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO fleet_accounts(account_id, email, owner_key, display_name, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (account_id, cleaned, owner_key, str(display_name or "").strip(), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise FleetAccountStoreError(f"an account for {cleaned!r} already exists") from exc
        return FleetAccount(account_id=account_id, email=cleaned, owner_key=owner_key, display_name=display_name, created_at=now, updated_at=now)

    def get_account_by_email(self, email: str) -> FleetAccount | None:
        cleaned = str(email or "").strip().lower()
        if not cleaned:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM fleet_accounts WHERE email = ?", (cleaned,)).fetchone()
        return FleetAccount(**dict(row)) if row else None

    def get_account(self, account_id: str) -> FleetAccount | None:
        aid = str(account_id or "").strip()
        if not aid:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM fleet_accounts WHERE account_id = ?", (aid,)).fetchone()
        return FleetAccount(**dict(row)) if row else None

    # -- passkeys -----------------------------------------------------------

    def add_passkey(self, account_id: str, credential_id: str, public_key: str, sign_count: int, transports: str = "") -> None:
        now = utc_now()
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO fleet_passkeys(credential_id, account_id, public_key, sign_count, transports, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (credential_id, account_id, public_key, int(sign_count), str(transports or ""), now),
                )
            except sqlite3.IntegrityError as exc:
                raise FleetAccountStoreError("this passkey is already registered") from exc

    def get_passkey(self, credential_id: str) -> FleetPasskey | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM fleet_passkeys WHERE credential_id = ?", (credential_id,)
            ).fetchone()
        return FleetPasskey(**dict(row)) if row else None

    def list_passkeys(self, account_id: str) -> list[FleetPasskey]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM fleet_passkeys WHERE account_id = ?", (account_id,)
            ).fetchall()
        return [FleetPasskey(**dict(r)) for r in rows]

    def update_sign_count(self, credential_id: str, sign_count: int) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE fleet_passkeys SET sign_count = ? WHERE credential_id = ?",
                (int(sign_count), credential_id),
            )

    # -- registration/login challenges --------------------------------------

    def store_challenge(self, email: str, kind: str, challenge: str) -> None:
        cleaned = _clean_email(email)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(minutes=CHALLENGE_TTL_MINUTES)).isoformat().replace("+00:00", "Z")
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fleet_challenges(email, kind, challenge, created_at, expires_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (cleaned, kind, challenge, utc_now(), expires),
            )

    def consume_challenge(self, email: str, kind: str) -> str | None:
        cleaned = str(email or "").strip().lower()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT challenge, expires_at FROM fleet_challenges WHERE email = ? AND kind = ?",
                (cleaned, kind),
            ).fetchone()
            conn.execute("DELETE FROM fleet_challenges WHERE email = ? AND kind = ?", (cleaned, kind))
        if row is None:
            return None
        expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_at:
            return None
        return str(row["challenge"])

    # -- sessions -------------------------------------------------------------

    def create_session(self, account_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(days=SESSION_TTL_DAYS)).isoformat().replace("+00:00", "Z")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO fleet_sessions(session_token, account_id, created_at, expires_at) VALUES(?, ?, ?, ?)",
                (token, account_id, utc_now(), expires),
            )
        return token

    def get_session_account(self, session_token: str) -> FleetAccount | None:
        token = str(session_token or "").strip()
        if not token:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT account_id, expires_at FROM fleet_sessions WHERE session_token = ?", (token,)
            ).fetchone()
            if row is None:
                return None
            expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                conn.execute("DELETE FROM fleet_sessions WHERE session_token = ?", (token,))
                return None
            account_row = conn.execute(
                "SELECT * FROM fleet_accounts WHERE account_id = ?", (row["account_id"],)
            ).fetchone()
        return FleetAccount(**dict(account_row)) if account_row else None

    def delete_session(self, session_token: str) -> None:
        token = str(session_token or "").strip()
        if not token:
            return
        with self._connection() as conn:
            conn.execute("DELETE FROM fleet_sessions WHERE session_token = ?", (token,))
