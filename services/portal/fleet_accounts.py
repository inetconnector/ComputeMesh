"""Durable portal login accounts for remote fleet administration.

Each account is authenticated by WebAuthn passkeys (no passwords) or secure
transactional magic-link recovery (via mesh@inetconnector.com) and owns a
generated fleet `owner_key` -- the same shared secret that nodes are configured with
to bind themselves to a fleet in services/billing/owner_accounts.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any

SCHEMA_VERSION = 2
CHALLENGE_TTL_MINUTES = 5
SESSION_TTL_DAYS = 30
MAGIC_LINK_TTL_MINUTES = 15
ENROLLMENT_TOKEN_TTL_MINUTES = 30


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
    nickname: str = ""
    last_used_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise FleetAccountStoreError("a valid email address is required")
    return email


class FleetAccountStore:
    """SQLite-backed passkey accounts, credentials, sessions, audit log and login challenges."""

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
                    created_at TEXT NOT NULL,
                    nickname TEXT NOT NULL DEFAULT '',
                    last_used_at TEXT NOT NULL DEFAULT ''
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
                CREATE TABLE IF NOT EXISTS fleet_recovery_tokens (
                    token_hash TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_fleet_recovery_email
                    ON fleet_recovery_tokens(email);

                CREATE TABLE IF NOT EXISTS fleet_enrollment_tokens (
                    token TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES fleet_accounts(account_id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS fleet_audit_log (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    ip_address TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fleet_audit_acc
                    ON fleet_audit_log(account_id, log_id DESC);

                CREATE TABLE IF NOT EXISTS fleet_key_rotations (
                    old_key TEXT PRIMARY KEY,
                    new_key TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    rotated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fleet_key_rot_acc
                    ON fleet_key_rotations(account_id);

                CREATE TABLE IF NOT EXISTS fleet_mcp_settings (
                    owner_id TEXT PRIMARY KEY,
                    disabled_tools TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fleet_banned_accounts (
                    owner_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    banned_at TEXT NOT NULL,
                    banned_by TEXT NOT NULL DEFAULT 'master_admin',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    unbanned_at TEXT,
                    unbanned_by TEXT,
                    unban_reason TEXT
                );
                """
            )
            # Safe schema migration for existing databases
            try:
                conn.execute("ALTER TABLE fleet_passkeys ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE fleet_passkeys ADD COLUMN last_used_at TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass

            conn.execute(
                "INSERT OR REPLACE INTO fleet_schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # -- accounts ---------------------------------------------------------

    def generate_secure_owner_key(self) -> str:
        """Generates a cryptographically secure, high-entropy unique owner key prefixed with 'inet-'."""
        for _ in range(10):
            candidate = "inet-" + secrets.token_hex(20)
            if self.get_account_by_owner_key(candidate) is None:
                return candidate
        raise FleetAccountStoreError("Konnte keinen eindeutigen Owner Key generieren. Bitte versuche es erneut.")

    def create_account(self, email: str, *, display_name: str = "") -> FleetAccount:
        cleaned = _clean_email(email)
        account_id = "facc_" + secrets.token_hex(12)
        owner_key = self.generate_secure_owner_key()
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

    def update_email(self, account_id: str, new_email: str) -> FleetAccount:
        """Updates the registered email address for an existing fleet account."""
        cleaned = _clean_email(new_email)
        now = utc_now()
        with self._connection() as conn:
            existing = conn.execute("SELECT account_id FROM fleet_accounts WHERE email = ?", (cleaned,)).fetchone()
            if existing and str(existing["account_id"]) != str(account_id):
                raise FleetAccountStoreError(f"Die E-Mail-Adresse {cleaned!r} wird bereits von einem anderen Konto verwendet.")

            acct_row = conn.execute("SELECT * FROM fleet_accounts WHERE account_id = ?", (account_id,)).fetchone()
            if not acct_row:
                raise FleetAccountStoreError(f"Account {account_id!r} wurde nicht gefunden.")

            old_email = str(acct_row["email"])
            conn.execute(
                "UPDATE fleet_accounts SET email = ?, updated_at = ? WHERE account_id = ?",
                (cleaned, now, account_id),
            )
            if old_email and old_email != cleaned:
                conn.execute("UPDATE fleet_challenges SET email = ? WHERE email = ?", (cleaned, old_email))
                conn.execute("UPDATE fleet_recovery_tokens SET email = ? WHERE email = ?", (cleaned, old_email))

            updated_row = conn.execute("SELECT * FROM fleet_accounts WHERE account_id = ?", (account_id,)).fetchone()
        return FleetAccount(**dict(updated_row))

    def rotate_owner_key(self, account_id: str, proposed_key: str | None = None) -> str:
        """Rotates the owner_key for a given fleet account.

        - If proposed_key is provided, strictly validates that:
          1. It starts with 'inet-'
          2. It is 24 to 128 characters long
          3. Contains only safe characters [a-zA-Z0-9_.-]
          4. Is NOT in use by any other fleet account
        - If proposed_key is None or empty, generates a safe CSPRNG 'inet-' key.
        """
        account = self.get_account(account_id)
        if account is None:
            raise FleetAccountStoreError(f"Account {account_id!r} wurde nicht gefunden.")

        old_key = account.owner_key
        cleaned_key = str(proposed_key or "").strip()
        if cleaned_key:
            if not cleaned_key.startswith("inet-"):
                raise FleetAccountStoreError("Der Owner Key muss zwingend mit dem Präfix 'inet-' beginnen.")
            if len(cleaned_key) < 24 or len(cleaned_key) > 128:
                raise FleetAccountStoreError("Der Owner Key muss zwischen 24 und 128 Zeichen lang sein.")
            if not re.match(r"^inet-[a-zA-Z0-9_\-\.]{19,123}$", cleaned_key):
                raise FleetAccountStoreError("Der Owner Key enthält ungültige Zeichen. Erlaubt sind nur: a-z, A-Z, 0-9, -, _, .")
            existing = self.get_account_by_owner_key(cleaned_key)
            if existing is not None and existing.account_id != account_id:
                raise FleetAccountStoreError("Dieser Owner Key ist bereits bei einem anderen Benutzer in Verwendung.")
            new_key = cleaned_key
        else:
            new_key = self.generate_secure_owner_key()

        now = utc_now()
        with self._connection() as conn:
            conn.execute(
                "UPDATE fleet_accounts SET owner_key = ?, updated_at = ? WHERE account_id = ?",
                (new_key, now, account_id),
            )
            if old_key and old_key != new_key:
                conn.execute(
                    "INSERT OR REPLACE INTO fleet_key_rotations(old_key, new_key, account_id, rotated_at) VALUES(?, ?, ?, ?)",
                    (old_key, new_key, account_id, now),
                )
                conn.execute(
                    "UPDATE fleet_key_rotations SET new_key = ? WHERE new_key = ? AND account_id = ?",
                    (new_key, old_key, account_id),
                )
        return new_key

    def resolve_latest_owner_key(self, key: str) -> str:
        """Resolves an old/historical owner_key to its current active rotated key, or returns the key if active."""
        cleaned = str(key or "").strip()
        if not cleaned:
            return ""
        with self._connection() as conn:
            row = conn.execute("SELECT new_key FROM fleet_key_rotations WHERE old_key = ?", (cleaned,)).fetchone()
            if row:
                return str(row["new_key"])
            acct = conn.execute("SELECT owner_key FROM fleet_accounts WHERE owner_key = ?", (cleaned,)).fetchone()
            if acct:
                return str(acct["owner_key"])
        return ""

    def get_account_by_email(self, email: str) -> FleetAccount | None:
        cleaned = str(email or "").strip().lower()
        if not cleaned:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM fleet_accounts WHERE email = ?", (cleaned,)).fetchone()
        return FleetAccount(**dict(row)) if row else None

    def get_account_by_owner_key(self, owner_key: str) -> FleetAccount | None:
        cleaned = str(owner_key or "").strip()
        if not cleaned:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM fleet_accounts WHERE owner_key = ?", (cleaned,)).fetchone()
        return FleetAccount(**dict(row)) if row else None

    def get_account(self, account_id: str) -> FleetAccount | None:
        aid = str(account_id or "").strip()
        if not aid:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM fleet_accounts WHERE account_id = ?", (aid,)).fetchone()
        return FleetAccount(**dict(row)) if row else None

    # -- passkeys -----------------------------------------------------------

    def add_passkey(self, account_id: str, credential_id: str, public_key: str, sign_count: int, transports: str = "", nickname: str = "") -> None:
        now = utc_now()
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO fleet_passkeys(credential_id, account_id, public_key, sign_count, transports, created_at, nickname, last_used_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (credential_id, account_id, public_key, int(sign_count), str(transports or ""), now, str(nickname or "").strip(), now),
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
                "SELECT * FROM fleet_passkeys WHERE account_id = ? ORDER BY created_at ASC", (account_id,)
            ).fetchall()
        return [FleetPasskey(**dict(r)) for r in rows]

    def update_sign_count(self, credential_id: str, sign_count: int) -> None:
        now = utc_now()
        with self._connection() as conn:
            conn.execute(
                "UPDATE fleet_passkeys SET sign_count = ?, last_used_at = ? WHERE credential_id = ?",
                (int(sign_count), now, credential_id),
            )

    def rename_passkey(self, account_id: str, credential_id: str, nickname: str) -> bool:
        with self._connection() as conn:
            cur = conn.execute(
                "UPDATE fleet_passkeys SET nickname = ? WHERE account_id = ? AND credential_id = ?",
                (str(nickname or "").strip(), account_id, credential_id),
            )
            return cur.rowcount > 0

    def delete_passkey(self, account_id: str, credential_id: str) -> bool:
        with self._connection() as conn:
            cur = conn.execute(
                "DELETE FROM fleet_passkeys WHERE account_id = ? AND credential_id = ?",
                (account_id, credential_id),
            )
            return cur.rowcount > 0

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

    # -- magic links & recovery tokens --------------------------------------

    def create_magic_link_token(self, email: str, ttl_minutes: int = MAGIC_LINK_TTL_MINUTES) -> str:
        cleaned = _clean_email(email)
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(minutes=ttl_minutes)).isoformat().replace("+00:00", "Z")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO fleet_recovery_tokens(token_hash, email, created_at, expires_at, consumed) "
                "VALUES(?, ?, ?, ?, 0)",
                (token_hash, cleaned, utc_now(), expires),
            )
        return raw_token

    def verify_magic_link_token(self, raw_token: str) -> FleetAccount | None:
        token = str(raw_token or "").strip()
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT email, expires_at, consumed FROM fleet_recovery_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None or row["consumed"]:
                return None
            conn.execute("UPDATE fleet_recovery_tokens SET consumed = 1 WHERE token_hash = ?", (token_hash,))
            expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                return None
            email = row["email"]
            account_row = conn.execute("SELECT * FROM fleet_accounts WHERE email = ?", (email,)).fetchone()
            if account_row is None:
                # First time magic link registration
                account_id = "facc_" + secrets.token_hex(12)
                owner_key = self.generate_secure_owner_key()
                now_str = utc_now()
                conn.execute(
                    "INSERT INTO fleet_accounts(account_id, email, owner_key, display_name, created_at, updated_at) "
                    "VALUES(?, ?, ?, '', ?, ?)",
                    (account_id, email, owner_key, now_str, now_str),
                )
                account_row = conn.execute("SELECT * FROM fleet_accounts WHERE account_id = ?", (account_id,)).fetchone()
        return FleetAccount(**dict(account_row)) if account_row else None

    # -- enrollment tokens --------------------------------------------------

    def create_enrollment_token(self, account_id: str, ttl_minutes: int = ENROLLMENT_TOKEN_TTL_MINUTES) -> str:
        token = "cmenroll_" + secrets.token_urlsafe(20)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(minutes=ttl_minutes)).isoformat().replace("+00:00", "Z")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO fleet_enrollment_tokens(token, account_id, created_at, expires_at, used) VALUES(?, ?, ?, ?, 0)",
                (token, account_id, utc_now(), expires),
            )
        return token

    def verify_and_consume_enrollment_token(self, token: str) -> str | None:
        """Verifies enrollment token and returns owner_key if valid."""
        raw = str(token or "").strip()
        if not raw:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT account_id, expires_at, used FROM fleet_enrollment_tokens WHERE token = ?",
                (raw,),
            ).fetchone()
            if row is None or row["used"]:
                return None
            conn.execute("UPDATE fleet_enrollment_tokens SET used = 1 WHERE token = ?", (raw,))
            expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                return None
            account = conn.execute("SELECT owner_key FROM fleet_accounts WHERE account_id = ?", (row["account_id"],)).fetchone()
            return str(account["owner_key"]) if account else None

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

    def revoke_all_sessions(self, account_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM fleet_sessions WHERE account_id = ?", (account_id,))

    # -- audit log ------------------------------------------------------------

    def record_audit_event(
        self,
        account_id: str,
        email: str,
        event_type: str,
        details: str = "",
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        now = utc_now()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO fleet_audit_log(account_id, email, event_type, details, ip_address, user_agent, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    account_id,
                    email,
                    event_type,
                    str(details or "").strip()[:500],
                    str(ip_address or "").strip()[:45],
                    str(user_agent or "").strip()[:255],
                    now,
                ),
            )

    def get_audit_log(self, account_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT log_id, event_type, details, ip_address, user_agent, created_at "
                "FROM fleet_audit_log WHERE account_id = ? ORDER BY log_id DESC LIMIT ?",
                (account_id, max(1, min(limit, 200))),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- mcp tool settings per fleet ------------------------------------------

    def get_mcp_disabled_tools(self, owner_id: str) -> list[str]:
        cleaned_id = str(owner_id or "").strip()
        if not cleaned_id:
            return []
        import json
        with self._connection() as conn:
            row = conn.execute(
                "SELECT disabled_tools FROM fleet_mcp_settings WHERE owner_id = ?",
                (cleaned_id,),
            ).fetchone()
            if not row:
                return []
            try:
                res = json.loads(row["disabled_tools"])
                return list(res) if isinstance(res, list) else []
            except Exception:
                return []

    def set_mcp_disabled_tools(self, owner_id: str, disabled_tools: list[str]) -> None:
        cleaned_id = str(owner_id or "").strip()
        if not cleaned_id:
            return
        import json
        clean_list = [str(t).strip() for t in (disabled_tools or []) if str(t).strip()]
        payload = json.dumps(clean_list)
        now = utc_now()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO fleet_mcp_settings(owner_id, disabled_tools, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET
                    disabled_tools = excluded.disabled_tools,
                    updated_at = excluded.updated_at
                """,
                (cleaned_id, payload, now),
            )

    # -- master admin fleet bans / permanent deactivations -------------------

    def ban_fleet(
        self,
        owner_id: str,
        reason: str = "Administrative suspension",
        banned_by: str = "master_admin",
    ) -> dict[str, Any]:
        """Permanently bans / suspends a fleet account. Can be reactivated by unban_fleet."""
        raw_id = str(owner_id or "").strip()
        if not raw_id:
            raise FleetAccountStoreError("owner_id or account identifier is required to ban fleet")

        canonical_id = raw_id
        acct = self.get_account(raw_id)
        if not acct:
            resolved_key = self.resolve_latest_owner_key(raw_id) or raw_id
            acct = self.get_account_by_owner_key(resolved_key)
        if acct:
            canonical_id = acct.account_id

        now = utc_now()
        clean_reason = str(reason or "Administrative suspension").strip()[:500]
        clean_admin = str(banned_by or "master_admin").strip()[:100]

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO fleet_banned_accounts(owner_id, reason, banned_at, banned_by, is_active, unbanned_at, unbanned_by, unban_reason)
                VALUES (?, ?, ?, ?, 1, NULL, NULL, NULL)
                ON CONFLICT(owner_id) DO UPDATE SET
                    reason = excluded.reason,
                    banned_at = excluded.banned_at,
                    banned_by = excluded.banned_by,
                    is_active = 1,
                    unbanned_at = NULL,
                    unbanned_by = NULL,
                    unban_reason = NULL
                """,
                (canonical_id, clean_reason, now, clean_admin),
            )
            if canonical_id != raw_id:
                conn.execute(
                    """
                    INSERT INTO fleet_banned_accounts(owner_id, reason, banned_at, banned_by, is_active, unbanned_at, unbanned_by, unban_reason)
                    VALUES (?, ?, ?, ?, 1, NULL, NULL, NULL)
                    ON CONFLICT(owner_id) DO UPDATE SET
                        reason = excluded.reason,
                        banned_at = excluded.banned_at,
                        banned_by = excluded.banned_by,
                        is_active = 1,
                        unbanned_at = NULL,
                        unbanned_by = NULL,
                        unban_reason = NULL
                    """,
                    (raw_id, clean_reason, now, clean_admin),
                )

        if acct:
            self.revoke_all_sessions(acct.account_id)
            self.record_audit_event(
                acct.account_id,
                acct.email,
                "FLEET_BANNED",
                f"Fleet suspended by {clean_admin}: {clean_reason}",
            )

        # Synchronize with in-memory DeadMansLeaseGuard immediately
        try:
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard()
            guard.trip_fleet(canonical_id, reason=f"ADMIN_BANNED: {clean_reason}")
            if canonical_id != raw_id:
                guard.trip_fleet(raw_id, reason=f"ADMIN_BANNED: {clean_reason}")
        except Exception:
            pass

        return {
            "owner_id": canonical_id,
            "status": "banned",
            "reason": clean_reason,
            "banned_at": now,
            "banned_by": clean_admin,
            "is_active": True,
        }

    def unban_fleet(
        self,
        owner_id: str,
        reason: str = "Administrative reactivation",
        unbanned_by: str = "master_admin",
    ) -> bool:
        """Reactivates / unbans a previously suspended fleet account."""
        raw_id = str(owner_id or "").strip()
        if not raw_id:
            return False

        canonical_id = raw_id
        acct = self.get_account(raw_id)
        if not acct:
            resolved_key = self.resolve_latest_owner_key(raw_id) or raw_id
            acct = self.get_account_by_owner_key(resolved_key)
        if acct:
            canonical_id = acct.account_id

        now = utc_now()
        clean_reason = str(reason or "Administrative reactivation").strip()[:500]
        clean_admin = str(unbanned_by or "master_admin").strip()[:100]

        with self._connection() as conn:
            cur = conn.execute(
                """
                UPDATE fleet_banned_accounts
                SET is_active = 0, unbanned_at = ?, unbanned_by = ?, unban_reason = ?
                WHERE (owner_id = ? OR owner_id = ?) AND is_active = 1
                """,
                (now, clean_admin, clean_reason, canonical_id, raw_id),
            )
            affected = cur.rowcount > 0

        if acct:
            self.record_audit_event(
                acct.account_id,
                acct.email,
                "FLEET_UNBANNED",
                f"Fleet reactivated by {clean_admin}: {clean_reason}",
            )

        # Synchronize with in-memory DeadMansLeaseGuard immediately
        try:
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard()
            guard.reset_fleet(canonical_id, reason=f"ADMIN_UNBANNED: {clean_reason}")
            if canonical_id != raw_id:
                guard.reset_fleet(raw_id, reason=f"ADMIN_UNBANNED: {clean_reason}")
        except Exception:
            pass

        return affected

    def is_fleet_banned(self, owner_id: str) -> bool:
        """Checks if a fleet account / owner ID / owner key is currently banned."""
        raw_id = str(owner_id or "").strip()
        if not raw_id:
            return False

        canonical_id = raw_id
        try:
            acct = self.get_account(raw_id)
            if not acct:
                resolved_key = self.resolve_latest_owner_key(raw_id) or raw_id
                acct = self.get_account_by_owner_key(resolved_key)
            if acct:
                canonical_id = acct.account_id
        except Exception:
            pass

        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM fleet_banned_accounts WHERE (owner_id = ? OR owner_id = ?) AND is_active = 1",
                (canonical_id, raw_id),
            ).fetchone()
            return row is not None

    def get_fleet_ban_info(self, owner_id: str) -> dict[str, Any] | None:
        """Returns ban details for a fleet account if actively banned, otherwise None."""
        raw_id = str(owner_id or "").strip()
        if not raw_id:
            return None

        canonical_id = raw_id
        try:
            acct = self.get_account(raw_id)
            if not acct:
                resolved_key = self.resolve_latest_owner_key(raw_id) or raw_id
                acct = self.get_account_by_owner_key(resolved_key)
            if acct:
                canonical_id = acct.account_id
        except Exception:
            pass

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT owner_id, reason, banned_at, banned_by, is_active, unbanned_at, unbanned_by, unban_reason
                FROM fleet_banned_accounts
                WHERE (owner_id = ? OR owner_id = ?) AND is_active = 1
                ORDER BY banned_at DESC LIMIT 1
                """,
                (canonical_id, raw_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_banned_fleets(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Lists all banned fleet accounts recorded in persistent storage."""
        with self._connection() as conn:
            query = (
                "SELECT owner_id, reason, banned_at, banned_by, is_active, unbanned_at, unbanned_by, unban_reason "
                "FROM fleet_banned_accounts "
            )
            if active_only:
                query += "WHERE is_active = 1 "
            query += "ORDER BY banned_at DESC"
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def sync_banned_fleets_to_guard(self) -> int:
        """Loads all active banned accounts from database into DeadMansLeaseGuard on startup."""
        banned = self.list_banned_fleets(active_only=True)
        count = 0
        try:
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard()
            for b in banned:
                oid = str(b.get("owner_id", "")).strip()
                reason = str(b.get("reason", "Administrative suspension")).strip()
                if oid:
                    guard.trip_fleet(oid, reason=f"ADMIN_BANNED: {reason}")
                    count += 1
        except Exception:
            pass
        return count

