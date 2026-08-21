from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import secrets
import sqlite3

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from protocol.node_identity import VerificationKey, key_id_from_public_key

MAX_ENROLLMENT_TOKEN_TTL = timedelta(minutes=15)


class IdentityStoreError(RuntimeError):
    pass


class EnrollmentTokenInvalid(IdentityStoreError):
    pass


class EnrollmentTokenExpired(IdentityStoreError):
    pass


class EnrollmentConflict(IdentityStoreError):
    pass


class IdentityAuthorizationError(IdentityStoreError):
    pass


@dataclass(frozen=True)
class EnrollmentResult:
    node_id: str
    principal_id: str
    key_id: str
    created: bool


@dataclass(frozen=True)
class NodeKeyState:
    node_id: str
    principal_id: str
    key_id: str
    status: str
    created_at: datetime
    revoked_at: datetime | None


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_key_hash(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()


def _validate_public_key(public_key: bytes) -> bytes:
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise ValueError("Ed25519 public key must be exactly 32 bytes")
    Ed25519PublicKey.from_public_bytes(public_key)
    return public_key


class SQLiteIdentityStore:
    """Reference M1 node enrollment/key registry.

    This stores public identity state only. It never stores node private keys.
    Caller authentication/authorization of provider principals is outside this
    reference store and must be enforced by the service boundary using it.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SQLiteIdentityStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS identity_schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO identity_schema_meta(key, value)
                VALUES ('schema_version', '1');

            CREATE TABLE IF NOT EXISTS node_identity (
                node_id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'revoked')),
                created_at TEXT NOT NULL,
                revoked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS node_key (
                key_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                algorithm TEXT NOT NULL CHECK(algorithm = 'ed25519'),
                public_key BLOB NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'revoked')),
                created_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(node_id) REFERENCES node_identity(node_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS node_key_node_idx ON node_key(node_id);

            CREATE TABLE IF NOT EXISTS enrollment_token (
                token_hash TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                consumed_node_id TEXT,
                consumed_key_id TEXT,
                consumed_public_key_hash TEXT
            );
            """
        )
        version = self._db.execute(
            "SELECT value FROM identity_schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        if version != "1":
            raise RuntimeError(f"unsupported identity-store schema version {version}")

    def create_enrollment_token(
        self,
        principal_id: str,
        *,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> str:
        if not (1 <= len(principal_id) <= 256):
            raise ValueError("principal_id must be 1..256 characters")
        now_value = now or datetime.now(timezone.utc)
        if now_value.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("enrollment token times must be timezone-aware")
        now_utc = now_value.astimezone(timezone.utc)
        expiry = expires_at.astimezone(timezone.utc)
        if expiry <= now_utc:
            raise ValueError("enrollment token expiry must be in the future")
        if expiry - now_utc > MAX_ENROLLMENT_TOKEN_TTL:
            raise ValueError("enrollment token ttl must be <= 15 minutes")
        token = "enr_" + secrets.token_urlsafe(32)
        self._db.execute(
            "INSERT INTO enrollment_token(token_hash, principal_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (_token_hash(token), principal_id, _utc_text(now_utc), _utc_text(expiry)),
        )
        return token

    def enroll(
        self,
        token: str,
        public_key: bytes,
        *,
        now: datetime | None = None,
    ) -> EnrollmentResult:
        if not isinstance(token, str) or not (1 <= len(token) <= 256):
            raise EnrollmentTokenInvalid("invalid enrollment token")
        public_key = _validate_public_key(public_key)
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        token_hash = _token_hash(token)
        pub_hash = _public_key_hash(public_key)

        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT * FROM enrollment_token WHERE token_hash=?", (token_hash,)
            ).fetchone()
            if row is None:
                raise EnrollmentTokenInvalid("unknown enrollment token")
            if row["consumed_at"] is not None:
                if row["consumed_public_key_hash"] != pub_hash:
                    raise EnrollmentConflict(
                        "enrollment token was already consumed with a different public key"
                    )
                result = EnrollmentResult(
                    row["consumed_node_id"],
                    row["principal_id"],
                    row["consumed_key_id"],
                    False,
                )
                self._db.execute("COMMIT")
                return result
            expires_at = _parse_utc(row["expires_at"])
            assert expires_at is not None
            if expires_at <= now_utc:
                raise EnrollmentTokenExpired("enrollment token has expired")

            key_id = key_id_from_public_key(public_key)
            existing_key = self._db.execute(
                "SELECT node_id FROM node_key WHERE key_id=?", (key_id,)
            ).fetchone()
            if existing_key is not None:
                raise EnrollmentConflict("public key is already bound to another node")
            node_id = "node_" + secrets.token_hex(16)
            now_text = _utc_text(now_utc)
            self._db.execute(
                "INSERT INTO node_identity(node_id, principal_id, status, created_at) "
                "VALUES (?, ?, 'active', ?)",
                (node_id, row["principal_id"], now_text),
            )
            self._db.execute(
                "INSERT INTO node_key(key_id, node_id, algorithm, public_key, status, created_at) "
                "VALUES (?, ?, 'ed25519', ?, 'active', ?)",
                (key_id, node_id, public_key, now_text),
            )
            self._db.execute(
                "UPDATE enrollment_token SET consumed_at=?, consumed_node_id=?, "
                "consumed_key_id=?, consumed_public_key_hash=? WHERE token_hash=?",
                (now_text, node_id, key_id, pub_hash, token_hash),
            )
            self._db.execute("COMMIT")
            return EnrollmentResult(node_id, row["principal_id"], key_id, True)
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _require_node_principal(self, node_id: str, principal_id: str) -> sqlite3.Row:
        row = self._db.execute(
            "SELECT * FROM node_identity WHERE node_id=?", (node_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown node {node_id!r}")
        if row["principal_id"] != principal_id:
            raise IdentityAuthorizationError("principal does not own node")
        if row["status"] != "active":
            raise IdentityAuthorizationError("node is revoked")
        return row

    def rotate_key(
        self,
        node_id: str,
        principal_id: str,
        public_key: bytes,
        *,
        revoke_previous: bool = True,
        now: datetime | None = None,
    ) -> NodeKeyState:
        public_key = _validate_public_key(public_key)
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        key_id = key_id_from_public_key(public_key)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._require_node_principal(node_id, principal_id)
            existing = self._db.execute(
                "SELECT * FROM node_key WHERE key_id=?", (key_id,)
            ).fetchone()
            if existing is not None and existing["node_id"] != node_id:
                raise EnrollmentConflict("public key is already bound to another node")
            now_text = _utc_text(now_utc)
            if existing is None:
                self._db.execute(
                    "INSERT INTO node_key(key_id, node_id, algorithm, public_key, status, created_at) "
                    "VALUES (?, ?, 'ed25519', ?, 'active', ?)",
                    (key_id, node_id, public_key, now_text),
                )
            elif existing["status"] == "revoked":
                raise EnrollmentConflict("a revoked key cannot be reactivated")
            if revoke_previous:
                self._db.execute(
                    "UPDATE node_key SET status='revoked', revoked_at=? "
                    "WHERE node_id=? AND key_id<>? AND status='active'",
                    (now_text, node_id, key_id),
                )
            self._db.execute("COMMIT")
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        return self.get_key_state(node_id, key_id)

    def revoke_key(
        self,
        node_id: str,
        principal_id: str,
        key_id: str,
        *,
        now: datetime | None = None,
    ) -> NodeKeyState:
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._require_node_principal(node_id, principal_id)
        row = self._db.execute(
            "SELECT * FROM node_key WHERE node_id=? AND key_id=?", (node_id, key_id)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown key {key_id!r} for node {node_id!r}")
        if row["status"] != "revoked":
            self._db.execute(
                "UPDATE node_key SET status='revoked', revoked_at=? WHERE key_id=?",
                (_utc_text(now_utc), key_id),
            )
        return self.get_key_state(node_id, key_id)

    def revoke_node(
        self,
        node_id: str,
        principal_id: str,
        *,
        now: datetime | None = None,
    ) -> None:
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._require_node_principal(node_id, principal_id)
        now_text = _utc_text(now_utc)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                "UPDATE node_identity SET status='revoked', revoked_at=? WHERE node_id=?",
                (now_text, node_id),
            )
            self._db.execute(
                "UPDATE node_key SET status='revoked', revoked_at=COALESCE(revoked_at, ?) "
                "WHERE node_id=? AND status='active'",
                (now_text, node_id),
            )
            self._db.execute("COMMIT")
        except Exception:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def get_key_state(self, node_id: str, key_id: str) -> NodeKeyState:
        row = self._db.execute(
            "SELECT k.node_id, n.principal_id, k.key_id, k.status, k.created_at, k.revoked_at "
            "FROM node_key k JOIN node_identity n ON n.node_id=k.node_id "
            "WHERE k.node_id=? AND k.key_id=?",
            (node_id, key_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown key {key_id!r} for node {node_id!r}")
        created_at = _parse_utc(row["created_at"])
        assert created_at is not None
        return NodeKeyState(
            node_id=row["node_id"],
            principal_id=row["principal_id"],
            key_id=row["key_id"],
            status=row["status"],
            created_at=created_at,
            revoked_at=_parse_utc(row["revoked_at"]),
        )

    def resolve_key(self, node_id: str, key_id: str) -> VerificationKey:
        row = self._db.execute(
            "SELECT k.node_id, n.principal_id, k.key_id, k.public_key, "
            "k.status AS key_status, n.status AS node_status "
            "FROM node_key k JOIN node_identity n ON n.node_id=k.node_id "
            "WHERE k.node_id=? AND k.key_id=?",
            (node_id, key_id),
        ).fetchone()
        if row is None or row["key_status"] != "active" or row["node_status"] != "active":
            raise KeyError("unknown or unavailable node key")
        return VerificationKey(
            node_id=row["node_id"],
            principal_id=row["principal_id"],
            key_id=row["key_id"],
            public_key=bytes(row["public_key"]),
            active=True,
        )
