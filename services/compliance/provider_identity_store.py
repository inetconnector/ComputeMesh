"""SQLite persistent storage for ComputeMesh Provider & Trader Identities.

Follows durable, audited storage patterns and handles schema initialization,
material legal change detection, evidence tracking, declaration records,
fleet bindings, operator legal profiles, and statutory retention lifecycle execution.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Any, Iterator

from .dsa_policy import PlatformEnterpriseSize, PlatformOperatorLegalProfile
from .provider_identity import (
    BusinessRegistryInfo,
    EntityType,
    EvidenceConfidence,
    EvidenceSource,
    IdentityEvidence,
    IdentityVerificationState,
    LegalDeclaration,
    MarketplaceMode,
    ProviderIdentity,
    StructuredAddress,
    TraderDeclaration,
    VerificationState,
    utc_now,
)
from .retention_policy import RetentionAction, RetentionCategory, RetentionEngine

SCHEMA_VERSION = 2


class ProviderIdentityStoreError(Exception):
    """Raised when an identity store operation fails or invariants are violated."""


class ProviderIdentityStore:
    """Durable SQLite source of truth for Provider & Trader identities."""

    def __init__(self, storage_path: Path | str) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.storage_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_identities (
                    provider_identity_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL UNIQUE,
                    entity_type TEXT NOT NULL CHECK(entity_type IN ('individual', 'business')),
                    legal_name TEXT NOT NULL,
                    trade_name TEXT,
                    legal_representative TEXT,
                    acting_person_relationship TEXT,
                    address_line1 TEXT NOT NULL,
                    address_line2 TEXT,
                    postal_code TEXT NOT NULL,
                    city TEXT NOT NULL,
                    state_province TEXT,
                    country_code TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT,
                    registry_country TEXT,
                    registry_name TEXT,
                    registration_number TEXT,
                    vat_id TEXT,
                    verification_state TEXT NOT NULL,
                    state_reason TEXT,
                    stripe_account_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    verified_at TEXT,
                    schema_version INTEGER NOT NULL DEFAULT 2
                );
                CREATE INDEX IF NOT EXISTS idx_provider_identities_acc
                    ON provider_identities(account_id);

                CREATE TABLE IF NOT EXISTS provider_identity_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    provider_identity_id TEXT NOT NULL REFERENCES provider_identities(provider_identity_id) ON DELETE CASCADE,
                    field_scope TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    expires_at TEXT,
                    evidence_reference TEXT NOT NULL DEFAULT '',
                    verification_method TEXT NOT NULL DEFAULT '',
                    confidence TEXT NOT NULL DEFAULT 'SELF_REPORTED'
                );
                CREATE INDEX IF NOT EXISTS idx_provider_evidence_prv
                    ON provider_identity_evidence(provider_identity_id);

                CREATE TABLE IF NOT EXISTS provider_trader_declarations (
                    declaration_id TEXT PRIMARY KEY,
                    provider_identity_id TEXT NOT NULL REFERENCES provider_identities(provider_identity_id) ON DELETE CASCADE,
                    account_id TEXT NOT NULL,
                    declaration_type TEXT NOT NULL DEFAULT 'DSA_ART30_TRADER_COMMITMENT',
                    legal_text_version TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    locale TEXT NOT NULL DEFAULT 'de',
                    ip_hash TEXT NOT NULL DEFAULT '',
                    text_hash TEXT NOT NULL DEFAULT '',
                    applicability_context TEXT NOT NULL DEFAULT 'PUBLIC_MARKETPLACE',
                    audit_reference TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_provider_decl_prv
                    ON provider_trader_declarations(provider_identity_id);

                CREATE TABLE IF NOT EXISTS provider_identity_audit_log (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_identity_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    previous_state TEXT NOT NULL DEFAULT '',
                    new_state TEXT NOT NULL DEFAULT '',
                    reason TEXT,
                    request_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_provider_audit_prv
                    ON provider_identity_audit_log(provider_identity_id, log_id DESC);

                CREATE TABLE IF NOT EXISTS fleet_provider_bindings (
                    fleet_id TEXT PRIMARY KEY,
                    provider_identity_id TEXT NOT NULL REFERENCES provider_identities(provider_identity_id) ON DELETE CASCADE,
                    account_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'active', 'suspended', 'legacy_unverified')),
                    marketplace_mode TEXT NOT NULL DEFAULT 'PUBLIC_INTERMEDIARY',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_fleet_bindings_prv
                    ON fleet_provider_bindings(provider_identity_id);

                CREATE TABLE IF NOT EXISTS platform_operator_profile (
                    key TEXT PRIMARY KEY,
                    operator_name TEXT NOT NULL,
                    enterprise_size TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    notes TEXT
                );
                """
            )
            # Check migrations from schema version 1
            meta_row = conn.execute("SELECT value FROM provider_schema_meta WHERE key = 'schema_version'").fetchone()
            current_ver = int(meta_row["value"]) if meta_row else 1
            if current_ver < 2:
                # Add columns if upgrading from v1
                cols_decl = [c[1] for c in conn.execute("PRAGMA table_info(provider_trader_declarations)").fetchall()]
                if "declaration_type" not in cols_decl:
                    conn.execute("ALTER TABLE provider_trader_declarations ADD COLUMN declaration_type TEXT NOT NULL DEFAULT 'DSA_ART30_TRADER_COMMITMENT'")
                if "text_hash" not in cols_decl:
                    conn.execute("ALTER TABLE provider_trader_declarations ADD COLUMN text_hash TEXT NOT NULL DEFAULT ''")
                if "applicability_context" not in cols_decl:
                    conn.execute("ALTER TABLE provider_trader_declarations ADD COLUMN applicability_context TEXT NOT NULL DEFAULT 'PUBLIC_MARKETPLACE'")
                if "audit_reference" not in cols_decl:
                    conn.execute("ALTER TABLE provider_trader_declarations ADD COLUMN audit_reference TEXT NOT NULL DEFAULT ''")

                cols_evid = [c[1] for c in conn.execute("PRAGMA table_info(provider_identity_evidence)").fetchall()]
                if "confidence" not in cols_evid:
                    conn.execute("ALTER TABLE provider_identity_evidence ADD COLUMN confidence TEXT NOT NULL DEFAULT 'SELF_REPORTED'")

                cols_fleet = [c[1] for c in conn.execute("PRAGMA table_info(fleet_provider_bindings)").fetchall()]
                if "marketplace_mode" not in cols_fleet:
                    conn.execute("ALTER TABLE fleet_provider_bindings ADD COLUMN marketplace_mode TEXT NOT NULL DEFAULT 'PUBLIC_INTERMEDIARY'")

            conn.execute(
                "INSERT OR REPLACE INTO provider_schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _row_to_identity(row: sqlite3.Row) -> ProviderIdentity:
        entity_type = EntityType(str(row["entity_type"]))
        state_raw = str(row["verification_state"])
        identity_state = IdentityVerificationState(state_raw) if state_raw in IdentityVerificationState.__members__ else IdentityVerificationState.UNVERIFIED

        address = StructuredAddress(
            line1=str(row["address_line1"]),
            line2=str(row["address_line2"]) if row["address_line2"] else None,
            postal_code=str(row["postal_code"]),
            city=str(row["city"]),
            state_province=str(row["state_province"]) if row["state_province"] else None,
            country_code=str(row["country_code"]),
        )

        reg_info: BusinessRegistryInfo | None = None
        if row["registration_number"]:
            reg_info = BusinessRegistryInfo(
                registry_country=str(row["registry_country"] or row["country_code"]),
                registry_name=str(row["registry_name"] or ""),
                registration_number=str(row["registration_number"]),
            )

        return ProviderIdentity(
            provider_identity_id=str(row["provider_identity_id"]),
            account_id=str(row["account_id"]),
            entity_type=entity_type,
            legal_name=str(row["legal_name"]),
            trade_name=str(row["trade_name"]) if row["trade_name"] else None,
            legal_representative=str(row["legal_representative"]) if row["legal_representative"] else None,
            acting_person_relationship=str(row["acting_person_relationship"]) if row["acting_person_relationship"] else None,
            address=address,
            email=str(row["email"]),
            phone=str(row["phone"]) if row["phone"] else None,
            registry_info=reg_info,
            vat_id=str(row["vat_id"]) if row["vat_id"] else None,
            identity_state=identity_state,
            state_reason=str(row["state_reason"]) if row["state_reason"] else None,
            stripe_account_id=str(row["stripe_account_id"]) if row["stripe_account_id"] else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            verified_at=str(row["verified_at"]) if row["verified_at"] else None,
            schema_version=int(row["schema_version"]),
        )

    def get_identity_by_account(self, account_id: str) -> ProviderIdentity | None:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_identities WHERE account_id = ?", (account_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_identity(row)

    def get_identity(self, provider_identity_id: str) -> ProviderIdentity | None:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_identities WHERE provider_identity_id = ?", (provider_identity_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_identity(row)

    def upsert_identity(
        self,
        *,
        account_id: str,
        entity_type: EntityType | str,
        legal_name: str,
        address: StructuredAddress | dict[str, Any],
        email: str,
        trade_name: str | None = None,
        legal_representative: str | None = None,
        acting_person_relationship: str | None = None,
        phone: str | None = None,
        registry_info: BusinessRegistryInfo | dict[str, Any] | None = None,
        vat_id: str | None = None,
        stripe_account_id: str | None = None,
        actor: str = "user",
        request_id: str = "",
    ) -> ProviderIdentity:
        now = utc_now()
        et = EntityType(entity_type) if isinstance(entity_type, str) else entity_type
        addr = StructuredAddress.from_dict(address) if isinstance(address, dict) else address
        reg: BusinessRegistryInfo | None = None
        if isinstance(registry_info, dict) and registry_info.get("registration_number"):
            reg = BusinessRegistryInfo.from_dict(registry_info)
        elif isinstance(registry_info, BusinessRegistryInfo):
            reg = registry_info

        clean_legal_name = str(legal_name or "").strip()
        clean_email = str(email or "").strip().lower()
        if not clean_legal_name:
            raise ProviderIdentityStoreError("legal_name is required")
        if not clean_email or "@" not in clean_email:
            raise ProviderIdentityStoreError("valid email is required")

        with self._lock, self._connection() as conn:
            existing_row = conn.execute(
                "SELECT * FROM provider_identities WHERE account_id = ?", (account_id,)
            ).fetchone()

            if existing_row is None:
                prv_id = "prv_" + secrets.token_hex(12)
                initial_state = IdentityVerificationState.PENDING_REVIEW.value
                conn.execute(
                    """
                    INSERT INTO provider_identities(
                        provider_identity_id, account_id, entity_type, legal_name, trade_name,
                        legal_representative, acting_person_relationship,
                        address_line1, address_line2, postal_code, city, state_province, country_code,
                        email, phone, registry_country, registry_name, registration_number, vat_id,
                        verification_state, state_reason, stripe_account_id, created_at, updated_at,
                        verified_at, schema_version
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prv_id,
                        account_id,
                        et.value,
                        clean_legal_name,
                        trade_name.strip() if trade_name else None,
                        legal_representative.strip() if legal_representative else None,
                        acting_person_relationship.strip() if acting_person_relationship else None,
                        addr.line1,
                        addr.line2,
                        addr.postal_code,
                        addr.city,
                        addr.state_province,
                        addr.country_code,
                        clean_email,
                        phone.strip() if phone else None,
                        reg.registry_country if reg else None,
                        reg.registry_name if reg else None,
                        reg.registration_number if reg else None,
                        vat_id.strip() if vat_id else None,
                        initial_state,
                        None,
                        stripe_account_id.strip() if stripe_account_id else None,
                        now,
                        now,
                        None,
                        SCHEMA_VERSION,
                    ),
                )
                self._record_audit(
                    conn,
                    prv_id,
                    account_id,
                    actor=actor,
                    action="provider_identity_created",
                    previous_state="",
                    new_state=initial_state,
                    reason="Initial provider profile registration",
                    request_id=request_id,
                )
            else:
                existing = self._row_to_identity(existing_row)
                prv_id = existing.provider_identity_id
                prev_state = existing.identity_state

                material_change = (
                    existing.legal_name != clean_legal_name
                    or existing.entity_type != et
                    or existing.address.line1 != addr.line1
                    or existing.address.city != addr.city
                    or existing.address.postal_code != addr.postal_code
                    or existing.address.country_code != addr.country_code
                    or (existing.registry_info.registration_number if existing.registry_info else None)
                    != (reg.registration_number if reg else None)
                )

                if prev_state == IdentityVerificationState.VERIFIED and material_change:
                    new_state = IdentityVerificationState.REVERIFICATION_REQUIRED.value
                    verified_at = None
                    reason = "Material identity fields modified after verification"
                else:
                    new_state = prev_state.value
                    verified_at = existing.verified_at
                    reason = "Profile updated"

                conn.execute(
                    """
                    UPDATE provider_identities SET
                        entity_type = ?,
                        legal_name = ?,
                        trade_name = ?,
                        legal_representative = ?,
                        acting_person_relationship = ?,
                        address_line1 = ?,
                        address_line2 = ?,
                        postal_code = ?,
                        city = ?,
                        state_province = ?,
                        country_code = ?,
                        email = ?,
                        phone = ?,
                        registry_country = ?,
                        registry_name = ?,
                        registration_number = ?,
                        vat_id = ?,
                        verification_state = ?,
                        stripe_account_id = COALESCE(?, stripe_account_id),
                        updated_at = ?,
                        verified_at = ?
                    WHERE provider_identity_id = ?
                    """,
                    (
                        et.value,
                        clean_legal_name,
                        trade_name.strip() if trade_name else None,
                        legal_representative.strip() if legal_representative else None,
                        acting_person_relationship.strip() if acting_person_relationship else None,
                        addr.line1,
                        addr.line2,
                        addr.postal_code,
                        addr.city,
                        addr.state_province,
                        addr.country_code,
                        clean_email,
                        phone.strip() if phone else None,
                        reg.registry_country if reg else None,
                        reg.registry_name if reg else None,
                        reg.registration_number if reg else None,
                        vat_id.strip() if vat_id else None,
                        new_state,
                        stripe_account_id.strip() if stripe_account_id else None,
                        now,
                        verified_at,
                        prv_id,
                    ),
                )
                self._record_audit(
                    conn,
                    prv_id,
                    account_id,
                    actor=actor,
                    action="provider_identity_updated",
                    previous_state=prev_state.value,
                    new_state=new_state,
                    reason=reason,
                    request_id=request_id,
                )

            updated_row = conn.execute(
                "SELECT * FROM provider_identities WHERE provider_identity_id = ?", (prv_id,)
            ).fetchone()
            return self._row_to_identity(updated_row)

    def update_verification_state(
        self,
        provider_identity_id: str,
        new_state: IdentityVerificationState | VerificationState,
        *,
        actor: str,
        reason: str,
        request_id: str = "",
    ) -> ProviderIdentity:
        now = utc_now()
        with self._lock, self._connection() as conn:
            existing_row = conn.execute(
                "SELECT * FROM provider_identities WHERE provider_identity_id = ?", (provider_identity_id,)
            ).fetchone()
            if existing_row is None:
                raise ProviderIdentityStoreError(f"Provider {provider_identity_id!r} does not exist")

            prev_state = str(existing_row["verification_state"])
            verified_at = now if new_state == IdentityVerificationState.VERIFIED else (
                existing_row["verified_at"] if new_state != IdentityVerificationState.UNVERIFIED else None
            )

            conn.execute(
                """
                UPDATE provider_identities SET
                    verification_state = ?,
                    state_reason = ?,
                    verified_at = ?,
                    updated_at = ?
                WHERE provider_identity_id = ?
                """,
                (new_state.value, reason, verified_at, now, provider_identity_id),
            )

            self._record_audit(
                conn,
                provider_identity_id,
                str(existing_row["account_id"]),
                actor=actor,
                action="verification_state_transition",
                previous_state=prev_state,
                new_state=new_state.value,
                reason=reason,
                request_id=request_id,
            )

            updated_row = conn.execute(
                "SELECT * FROM provider_identities WHERE provider_identity_id = ?", (provider_identity_id,)
            ).fetchone()
            return self._row_to_identity(updated_row)

    def add_evidence(
        self,
        *,
        provider_identity_id: str,
        field_scope: str,
        source: EvidenceSource | str,
        status: str = "valid",
        verification_method: str = "automated",
        confidence: EvidenceConfidence | str = EvidenceConfidence.SELF_REPORTED,
        evidence_reference: str = "",
        expires_at: str | None = None,
    ) -> IdentityEvidence:
        ev_source = EvidenceSource(source) if isinstance(source, str) and source in EvidenceSource.__members__ else EvidenceSource.SELF_ATTESTATION
        ev_conf = EvidenceConfidence(confidence) if isinstance(confidence, str) and confidence in EvidenceConfidence.__members__ else EvidenceConfidence.SELF_REPORTED
        now = utc_now()
        ev_id = "evid_" + secrets.token_hex(12)
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO provider_identity_evidence(
                    evidence_id, provider_identity_id, field_scope, source, status,
                    verified_at, expires_at, evidence_reference, verification_method, confidence
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev_id,
                    provider_identity_id,
                    field_scope,
                    ev_source.value,
                    status,
                    now,
                    expires_at,
                    evidence_reference,
                    verification_method,
                    ev_conf.value,
                ),
            )
        return IdentityEvidence(
            evidence_id=ev_id,
            provider_identity_id=provider_identity_id,
            field_scope=field_scope,
            source=ev_source,
            status=status,
            verified_at=now,
            expires_at=expires_at,
            evidence_reference=evidence_reference,
            verification_method=verification_method,
            confidence=ev_conf,
        )

    def list_evidence(self, provider_identity_id: str) -> list[IdentityEvidence]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM provider_identity_evidence WHERE provider_identity_id = ? ORDER BY verified_at DESC",
                (provider_identity_id,),
            ).fetchall()
            return [IdentityEvidence.from_dict(dict(r)) for r in rows]

    def record_declaration(
        self,
        *,
        provider_identity_id: str,
        account_id: str,
        legal_text_version: str,
        declaration_type: str = "DSA_ART30_TRADER_COMMITMENT",
        locale: str = "de",
        client_ip: str = "",
        text_hash: str = "",
        applicability_context: str = "PUBLIC_MARKETPLACE",
        audit_reference: str = "",
    ) -> LegalDeclaration:
        now = utc_now()
        decl_id = "decl_" + secrets.token_hex(12)
        ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:16] if client_ip else ""
        t_hash = text_hash or hashlib.sha256(f"{declaration_type}:{legal_text_version}".encode("utf-8")).hexdigest()[:16]
        audit_ref = audit_reference or f"audit_{secrets.token_hex(8)}"

        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO provider_trader_declarations(
                    declaration_id, provider_identity_id, account_id, declaration_type,
                    legal_text_version, accepted_at, locale, ip_hash, text_hash,
                    applicability_context, audit_reference
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decl_id,
                    provider_identity_id,
                    account_id,
                    declaration_type,
                    legal_text_version,
                    now,
                    locale,
                    ip_hash,
                    t_hash,
                    applicability_context,
                    audit_ref,
                ),
            )
            self._record_audit(
                conn,
                provider_identity_id,
                account_id,
                actor="user",
                action="legal_declaration_accepted",
                previous_state="",
                new_state="",
                reason=f"Accepted {declaration_type} (version {legal_text_version})",
            )
        return LegalDeclaration(
            declaration_id=decl_id,
            provider_identity_id=provider_identity_id,
            account_id=account_id,
            declaration_type=declaration_type,
            version=legal_text_version,
            accepted_at=now,
            text_hash=t_hash,
            locale=locale,
            applicability_context=applicability_context,
            audit_reference=audit_ref,
        )

    def list_declarations(self, provider_identity_id: str) -> list[LegalDeclaration]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM provider_trader_declarations WHERE provider_identity_id = ? ORDER BY accepted_at DESC",
                (provider_identity_id,),
            ).fetchall()
            return [LegalDeclaration.from_dict(dict(r)) for r in rows]

    def bind_fleet(
        self,
        *,
        fleet_id: str,
        provider_identity_id: str,
        account_id: str,
        status: str = "active",
        marketplace_mode: MarketplaceMode | str = MarketplaceMode.PUBLIC_INTERMEDIARY,
    ) -> dict[str, Any]:
        now = utc_now()
        clean_fleet_id = str(fleet_id or "").strip()
        if not clean_fleet_id:
            raise ProviderIdentityStoreError("fleet_id is required")
        mode_str = marketplace_mode.value if isinstance(marketplace_mode, MarketplaceMode) else str(marketplace_mode)

        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO fleet_provider_bindings(
                    fleet_id, provider_identity_id, account_id, status, marketplace_mode, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fleet_id) DO UPDATE SET
                    provider_identity_id = excluded.provider_identity_id,
                    account_id = excluded.account_id,
                    status = excluded.status,
                    marketplace_mode = excluded.marketplace_mode,
                    updated_at = excluded.updated_at
                """,
                (clean_fleet_id, provider_identity_id, account_id, status, mode_str, now, now),
            )
            row = conn.execute(
                "SELECT * FROM fleet_provider_bindings WHERE fleet_id = ?", (clean_fleet_id,)
            ).fetchone()
            return dict(row)

    def get_fleet_binding(self, fleet_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM fleet_provider_bindings WHERE fleet_id = ?", (fleet_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_fleets_for_provider(self, provider_identity_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM fleet_provider_bindings WHERE provider_identity_id = ? ORDER BY created_at DESC",
                (provider_identity_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_operator_profile(self) -> PlatformOperatorLegalProfile:
        with self._lock, self._connection() as conn:
            row = conn.execute("SELECT * FROM platform_operator_profile WHERE key = 'primary'").fetchone()
            if row is None:
                return PlatformOperatorLegalProfile.from_environment()
            size_str = str(row["enterprise_size"])
            size = PlatformEnterpriseSize[size_str] if size_str in PlatformEnterpriseSize.__members__ else PlatformEnterpriseSize.UNKNOWN
            return PlatformOperatorLegalProfile(
                operator_name=str(row["operator_name"]),
                enterprise_size=size,
                jurisdiction=str(row["jurisdiction"]),
                evaluated_at=str(row["evaluated_at"]),
                notes=str(row["notes"]) if row["notes"] else None,
            )

    def save_operator_profile(self, profile: PlatformOperatorLegalProfile) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO platform_operator_profile(
                    key, operator_name, enterprise_size, jurisdiction, evaluated_at, notes
                ) VALUES('primary', ?, ?, ?, ?, ?)
                """,
                (
                    profile.operator_name,
                    profile.enterprise_size.value,
                    profile.jurisdiction,
                    profile.evaluated_at or utc_now(),
                    profile.notes,
                ),
            )

    def apply_retention_lifecycle(self, now: datetime | None = None) -> dict[str, int]:
        """Executes statutory and privacy retention lifecycle rules against stored records."""
        current_time = now or datetime.now(timezone.utc)
        results = {
            "purged_draft_profiles": 0,
            "anonymized_audit_logs": 0,
            "purged_terminated_trader_records": 0,
        }

        # 1. Inactive draft profiles (> 90 days without bound fleets)
        rule_draft = RetentionEngine.get_rule(RetentionCategory.INACTIVE_DRAFT_PROFILES)
        cutoff_draft = (current_time - timedelta(days=rule_draft.duration_days or 90)).isoformat().replace("+00:00", "Z")

        with self._lock, self._connection() as conn:
            stale_drafts = conn.execute(
                """
                SELECT provider_identity_id FROM provider_identities
                WHERE verification_state = 'INCOMPLETE'
                  AND created_at < ?
                  AND provider_identity_id NOT IN (SELECT provider_identity_id FROM fleet_provider_bindings)
                """,
                (cutoff_draft,),
            ).fetchall()

            for row in stale_drafts:
                pid = row["provider_identity_id"]
                conn.execute("DELETE FROM provider_identities WHERE provider_identity_id = ?", (pid,))
                results["purged_draft_profiles"] += 1

            # 2. Security audit logs (> 365 days)
            rule_audit = RetentionEngine.get_rule(RetentionCategory.SECURITY_AUDIT_LOGS)
            cutoff_audit = (current_time - timedelta(days=rule_audit.duration_days or 365)).isoformat().replace("+00:00", "Z")

            audit_rows = conn.execute(
                "SELECT log_id FROM provider_identity_audit_log WHERE created_at < ?",
                (cutoff_audit,),
            ).fetchall()
            if audit_rows:
                conn.execute(
                    "UPDATE provider_identity_audit_log SET account_id = 'anonymized', actor = 'anonymized', reason = 'anonymized per retention policy' WHERE created_at < ?",
                    (cutoff_audit,),
                )
                results["anonymized_audit_logs"] += len(audit_rows)

        return results

    @staticmethod
    def _record_audit(
        conn: sqlite3.Connection,
        provider_identity_id: str,
        account_id: str,
        *,
        actor: str,
        action: str,
        previous_state: str = "",
        new_state: str = "",
        reason: str | None = None,
        request_id: str = "",
    ) -> None:
        conn.execute(
            """
            INSERT INTO provider_identity_audit_log(
                provider_identity_id, account_id, actor, action,
                previous_state, new_state, reason, request_id, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider_identity_id,
                account_id,
                actor,
                action,
                previous_state,
                new_state,
                reason,
                request_id,
                utc_now(),
            ),
        )

    def list_audit_log(self, provider_identity_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM provider_identity_audit_log WHERE provider_identity_id = ? ORDER BY log_id DESC LIMIT ?",
                (provider_identity_id, max(1, min(100, limit))),
            ).fetchall()
            return [dict(r) for r in rows]
