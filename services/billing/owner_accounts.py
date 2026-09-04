"""Durable owner/resource mappings for unified ComputeMesh accounts.

This module intentionally stores account/resource relationships rather than API-key
secrets. API credentials remain in the gateway credential store; callers bind an
opaque credential id to one owner. Provider node and verified-device ownership is
kept durable so earnings, promo eligibility and payout state do not depend on an
e-mail address, node name or local OS installation.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


SCHEMA_VERSION = 1
PROMO_DEVICE = "device_onboarding"
PROMO_GPU = "gpu_onboarding"


class OwnerAccountStoreError(Exception):
    """Raised when owner/resource state would become ambiguous or unsafe."""


@dataclass(frozen=True)
class OwnerAccount:
    owner_id: str
    display_name: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PromoClaim:
    claim_id: str
    owner_id: str
    claim_class: str
    hardware_claim_id: str
    amount_micro_units: int
    policy_version: str
    created_at: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_identifier(value: str, *, field: str, max_len: int = 256) -> str:
    result = str(value or "").strip()
    if not result:
        raise OwnerAccountStoreError(f"{field} is required")
    if len(result) > max_len:
        raise OwnerAccountStoreError(f"{field} exceeds {max_len} characters")
    return result


class OwnerAccountStore:
    """SQLite-backed mapping of owners to credentials, nodes and verified devices.

    The store is deliberately conservative:
    - one provider node can belong to only one owner at a time;
    - one device claim id can belong to only one owner at a time;
    - one onboarding claim class can be granted only once per owner;
    - one physical claim id cannot fund the same promo class for multiple owners.

    Rebinding is a separate audited workflow and is not implemented as an implicit
    upsert because silently moving hardware between owners would create accounting
    and promo-abuse risk.
    """

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
                CREATE TABLE IF NOT EXISTS owner_schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS owner_accounts (
                    owner_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS owner_api_credentials (
                    credential_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES owner_accounts(owner_id)
                );

                CREATE TABLE IF NOT EXISTS owner_provider_nodes (
                    provider_node_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES owner_accounts(owner_id)
                );

                CREATE TABLE IF NOT EXISTS owner_devices (
                    device_claim_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    assurance_tier TEXT NOT NULL DEFAULT 'UNVERIFIED',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES owner_accounts(owner_id)
                );

                CREATE TABLE IF NOT EXISTS owner_promo_claims (
                    claim_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    claim_class TEXT NOT NULL,
                    hardware_claim_id TEXT NOT NULL,
                    amount_micro_units INTEGER NOT NULL,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(owner_id, claim_class),
                    UNIQUE(hardware_claim_id, claim_class),
                    FOREIGN KEY(owner_id) REFERENCES owner_accounts(owner_id)
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO owner_schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def ensure_owner(self, owner_id: str, *, display_name: str = "") -> OwnerAccount:
        oid = _clean_identifier(owner_id, field="owner_id")
        now = utc_now()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM owner_accounts WHERE owner_id = ?",
                (oid,),
            ).fetchone()
            if row is None:
                try:
                    conn.execute(
                        "INSERT INTO owner_accounts(owner_id, display_name, created_at, updated_at) VALUES(?, ?, ?, ?)",
                        (oid, str(display_name or "").strip(), now, now),
                    )
                except sqlite3.IntegrityError:
                    # Concurrent request for the same owner_id (e.g. many
                    # nodes heartbeating into the shared default fleet) won
                    # the SELECT-then-INSERT race first; the row now exists.
                    pass
            elif display_name and str(display_name).strip() != row["display_name"]:
                conn.execute(
                    "UPDATE owner_accounts SET display_name = ?, updated_at = ? WHERE owner_id = ?",
                    (str(display_name).strip(), now, oid),
                )
            row = conn.execute(
                "SELECT * FROM owner_accounts WHERE owner_id = ?",
                (oid,),
            ).fetchone()
        assert row is not None
        return OwnerAccount(**dict(row))

    def get_owner(self, owner_id: str) -> OwnerAccount | None:
        oid = str(owner_id or "").strip()
        if not oid:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM owner_accounts WHERE owner_id = ?",
                (oid,),
            ).fetchone()
        return OwnerAccount(**dict(row)) if row is not None else None

    def _bind_unique(self, *, table: str, key_column: str, key: str, owner_id: str) -> None:
        oid = _clean_identifier(owner_id, field="owner_id")
        resource_id = _clean_identifier(key, field=key_column, max_len=512)
        if self.get_owner(oid) is None:
            raise OwnerAccountStoreError(f"unknown owner {oid}")
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT owner_id FROM {table} WHERE {key_column} = ?",
                (resource_id,),
            ).fetchone()
            if row is not None:
                if row["owner_id"] != oid:
                    raise OwnerAccountStoreError(
                        f"{key_column} {resource_id!r} is already bound to another owner"
                    )
                return
            conn.execute(
                f"INSERT INTO {table}({key_column}, owner_id, created_at) VALUES(?, ?, ?)",
                (resource_id, oid, utc_now()),
            )

    def bind_api_credential(self, owner_id: str, credential_id: str) -> None:
        self._bind_unique(
            table="owner_api_credentials",
            key_column="credential_id",
            key=credential_id,
            owner_id=owner_id,
        )

    def bind_provider_node(self, owner_id: str, provider_node_id: str) -> None:
        self._bind_unique(
            table="owner_provider_nodes",
            key_column="provider_node_id",
            key=provider_node_id,
            owner_id=owner_id,
        )

    def unbind_provider_node(self, owner_id: str, provider_node_id: str) -> bool:
        oid = _clean_identifier(owner_id, field="owner_id")
        nid = _clean_identifier(provider_node_id, field="provider_node_id")
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM owner_provider_nodes WHERE provider_node_id = ? AND owner_id = ?",
                (nid, oid),
            )
            return cursor.rowcount > 0

    def bind_device(
        self,
        owner_id: str,
        device_claim_id: str,
        *,
        assurance_tier: str = "UNVERIFIED",
    ) -> None:
        oid = _clean_identifier(owner_id, field="owner_id")
        device_id = _clean_identifier(device_claim_id, field="device_claim_id", max_len=512)
        tier = _clean_identifier(assurance_tier, field="assurance_tier", max_len=64)
        if self.get_owner(oid) is None:
            raise OwnerAccountStoreError(f"unknown owner {oid}")
        now = utc_now()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT owner_id, assurance_tier FROM owner_devices WHERE device_claim_id = ?",
                (device_id,),
            ).fetchone()
            if row is not None and row["owner_id"] != oid:
                raise OwnerAccountStoreError(
                    f"device_claim_id {device_id!r} is already bound to another owner"
                )
            if row is None:
                conn.execute(
                    "INSERT INTO owner_devices(device_claim_id, owner_id, assurance_tier, created_at, updated_at) VALUES(?, ?, ?, ?, ?)",
                    (device_id, oid, tier, now, now),
                )
            else:
                conn.execute(
                    "UPDATE owner_devices SET assurance_tier = ?, updated_at = ? WHERE device_claim_id = ?",
                    (tier, now, device_id),
                )

    def owner_for_api_credential(self, credential_id: str) -> str | None:
        return self._owner_for(
            table="owner_api_credentials",
            key_column="credential_id",
            key=credential_id,
        )

    def owner_for_provider_node(self, provider_node_id: str) -> str | None:
        return self._owner_for(
            table="owner_provider_nodes",
            key_column="provider_node_id",
            key=provider_node_id,
        )

    def owner_for_device(self, device_claim_id: str) -> str | None:
        return self._owner_for(
            table="owner_devices",
            key_column="device_claim_id",
            key=device_claim_id,
        )

    def _owner_for(self, *, table: str, key_column: str, key: str) -> str | None:
        value = str(key or "").strip()
        if not value:
            return None
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT owner_id FROM {table} WHERE {key_column} = ?",
                (value,),
            ).fetchone()
        return str(row["owner_id"]) if row is not None else None

    def list_provider_nodes(self, owner_id: str) -> list[str]:
        oid = _clean_identifier(owner_id, field="owner_id")
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT provider_node_id FROM owner_provider_nodes WHERE owner_id = ? ORDER BY provider_node_id",
                (oid,),
            ).fetchall()
        return [str(row["provider_node_id"]) for row in rows]

    def record_promo_claim(
        self,
        *,
        claim_id: str,
        owner_id: str,
        claim_class: str,
        hardware_claim_id: str,
        amount_micro_units: int,
        policy_version: str,
    ) -> PromoClaim:
        cid = _clean_identifier(claim_id, field="claim_id", max_len=512)
        oid = _clean_identifier(owner_id, field="owner_id")
        cclass = _clean_identifier(claim_class, field="claim_class", max_len=64)
        hardware_id = _clean_identifier(
            hardware_claim_id,
            field="hardware_claim_id",
            max_len=512,
        )
        policy = _clean_identifier(policy_version, field="policy_version", max_len=128)
        if amount_micro_units <= 0:
            raise OwnerAccountStoreError("promo claim amount must be positive")
        if self.get_owner(oid) is None:
            raise OwnerAccountStoreError(f"unknown owner {oid}")

        now = utc_now()
        try:
            with self._connection() as conn:
                existing = conn.execute(
                    "SELECT * FROM owner_promo_claims WHERE claim_id = ?",
                    (cid,),
                ).fetchone()
                if existing is not None:
                    result = PromoClaim(**dict(existing))
                    expected = (
                        oid,
                        cclass,
                        hardware_id,
                        amount_micro_units,
                        policy,
                    )
                    actual = (
                        result.owner_id,
                        result.claim_class,
                        result.hardware_claim_id,
                        result.amount_micro_units,
                        result.policy_version,
                    )
                    if actual != expected:
                        raise OwnerAccountStoreError(
                            f"promo claim id {cid!r} was already used with different data"
                        )
                    return result

                conn.execute(
                    """
                    INSERT INTO owner_promo_claims(
                        claim_id, owner_id, claim_class, hardware_claim_id,
                        amount_micro_units, policy_version, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cid, oid, cclass, hardware_id, amount_micro_units, policy, now),
                )
                row = conn.execute(
                    "SELECT * FROM owner_promo_claims WHERE claim_id = ?",
                    (cid,),
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise OwnerAccountStoreError(
                "promo class was already claimed by this owner or hardware"
            ) from exc

        assert row is not None
        return PromoClaim(**dict(row))

    def promo_claim_for_owner(self, owner_id: str, claim_class: str) -> PromoClaim | None:
        oid = str(owner_id or "").strip()
        cclass = str(claim_class or "").strip()
        if not oid or not cclass:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM owner_promo_claims WHERE owner_id = ? AND claim_class = ?",
                (oid, cclass),
            ).fetchone()
        return PromoClaim(**dict(row)) if row is not None else None
