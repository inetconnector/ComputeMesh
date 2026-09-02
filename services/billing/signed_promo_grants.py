"""Fail-closed consumer for private control-plane promo grant decisions.

The private control plane decides promo eligibility and policy. The public runtime
accepts only a narrowly-scoped, Ed25519-signed grant envelope and applies it through
the durable owner claim store plus the append-only owner promo ledger.

Cross-store ordering is deliberate: the durable claim is recorded before the
financial grant. If a process stops between those writes, redelivery of the same
signed claim resumes the ledger grant. If the ledger write already happened,
DuplicateEventError makes redelivery idempotent.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from services.billing.ledger import DuplicateEventError, Ledger
from services.billing.owner_accounts import OwnerAccountStore, OwnerAccountStoreError, PromoClaim
from services.billing.owner_credits import OwnerCreditLedger

PROMO_DECISION_KIND = "computemesh.promo_grant.v1"
PROMO_CLAIM_ID_VERSION = "v1"
DEVICE_CLAIM = "device_onboarding"
GPU_CLAIM = "gpu_onboarding"
_ALLOWED_CLAIM_CLASSES = {DEVICE_CLAIM, GPU_CLAIM}
_REQUIRED_FIELDS = {
    "kind",
    "decision_id",
    "issued_at",
    "expires_at",
    "owner_id",
    "claim_id",
    "claim_class",
    "hardware_claim_id",
    "assurance_tier",
    "node_id",
    "amount_micro_units",
    "policy_version",
    "evidence_digest",
    "signature",
}
_REQUIRED_SIGNATURE_FIELDS = {"algorithm", "key_id", "value"}


class PromoGrantDecisionError(ValueError):
    """A signed promo decision is invalid, expired, untrusted, or inconsistent."""


@dataclass(frozen=True)
class PromoGrantDecision:
    decision_id: str
    issued_at: int
    expires_at: int
    owner_id: str
    claim_id: str
    claim_class: str
    hardware_claim_id: str
    assurance_tier: str
    node_id: str
    amount_micro_units: int
    policy_version: str
    evidence_digest: str
    key_id: str


@dataclass(frozen=True)
class PromoGrantApplyResult:
    owner_id: str
    claim_id: str
    claim_class: str
    amount_micro_units: int
    policy_version: str
    ledger_status: str
    claim: PromoClaim


def _bounded_text(value: Any, *, field: str, max_len: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_len:
        raise PromoGrantDecisionError(f"invalid {field}")
    return text


def _b64u_decode(value: str) -> bytes:
    text = _bounded_text(value, field="signature value", max_len=256)
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in text):
        raise PromoGrantDecisionError("invalid signature encoding")
    padded = text + "=" * ((4 - len(text) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise PromoGrantDecisionError("invalid signature encoding") from exc
    if len(raw) != 64:
        raise PromoGrantDecisionError("invalid Ed25519 signature length")
    return raw


def canonical_unsigned_envelope(envelope: Mapping[str, Any]) -> bytes:
    unsigned = dict(envelope)
    unsigned.pop("signature", None)
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def promo_claim_id(
    *,
    owner_id: str,
    claim_class: str,
    hardware_claim_id: str,
    policy_version: str,
) -> str:
    material = "\x00".join(
        (
            PROMO_CLAIM_ID_VERSION,
            str(owner_id).strip(),
            str(claim_class).strip(),
            str(hardware_claim_id).strip(),
            str(policy_version).strip(),
        )
    ).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return f"promo_claim_{PROMO_CLAIM_ID_VERSION}_{digest}"


class PromoDecisionVerifier:
    """Verify reduced promo decisions from trusted private control-plane keys."""

    def __init__(
        self,
        trusted_keys: Mapping[str, bytes | Ed25519PublicKey],
        *,
        max_lifetime_seconds: int = 300,
        clock_skew_seconds: int = 30,
    ) -> None:
        if max_lifetime_seconds <= 0 or clock_skew_seconds < 0:
            raise ValueError("invalid promo decision time policy")
        keys: dict[str, Ed25519PublicKey] = {}
        for key_id, value in trusted_keys.items():
            kid = str(key_id or "").strip()
            if not kid:
                raise ValueError("promo decision key_id must be non-empty")
            if isinstance(value, Ed25519PublicKey):
                keys[kid] = value
            else:
                raw = bytes(value)
                if len(raw) != 32:
                    raise ValueError("promo decision Ed25519 public keys must be 32 bytes")
                keys[kid] = Ed25519PublicKey.from_public_bytes(raw)
        if not keys:
            raise ValueError("at least one trusted promo decision key is required")
        self._keys = keys
        self.max_lifetime_seconds = int(max_lifetime_seconds)
        self.clock_skew_seconds = int(clock_skew_seconds)

    def verify(
        self,
        envelope: Mapping[str, Any],
        *,
        now: int | float | None = None,
    ) -> PromoGrantDecision:
        if not isinstance(envelope, Mapping) or set(envelope) != _REQUIRED_FIELDS:
            raise PromoGrantDecisionError("promo decision has unknown or missing fields")
        if envelope.get("kind") != PROMO_DECISION_KIND:
            raise PromoGrantDecisionError("unsupported promo decision kind")

        signature = envelope.get("signature")
        if not isinstance(signature, Mapping) or set(signature) != _REQUIRED_SIGNATURE_FIELDS:
            raise PromoGrantDecisionError("invalid promo decision signature object")
        if signature.get("algorithm") != "Ed25519":
            raise PromoGrantDecisionError("unsupported promo decision signature algorithm")
        key_id = _bounded_text(signature.get("key_id"), field="signature key_id", max_len=128)
        public_key = self._keys.get(key_id)
        if public_key is None:
            raise PromoGrantDecisionError("promo decision was signed by an untrusted key")
        signature_bytes = _b64u_decode(str(signature.get("value") or ""))
        try:
            public_key.verify(signature_bytes, canonical_unsigned_envelope(envelope))
        except InvalidSignature as exc:
            raise PromoGrantDecisionError("invalid promo decision signature") from exc

        issued_at = envelope.get("issued_at")
        expires_at = envelope.get("expires_at")
        amount = envelope.get("amount_micro_units")
        if isinstance(issued_at, bool) or not isinstance(issued_at, int):
            raise PromoGrantDecisionError("issued_at must be integer epoch seconds")
        if isinstance(expires_at, bool) or not isinstance(expires_at, int):
            raise PromoGrantDecisionError("expires_at must be integer epoch seconds")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise PromoGrantDecisionError("amount_micro_units must be a positive integer")
        if expires_at <= issued_at or expires_at - issued_at > self.max_lifetime_seconds:
            raise PromoGrantDecisionError("promo decision lifetime exceeds policy")
        current = int(time.time() if now is None else now)
        if issued_at > current + self.clock_skew_seconds:
            raise PromoGrantDecisionError("promo decision was issued too far in the future")
        if expires_at <= current:
            raise PromoGrantDecisionError("promo decision has expired")

        owner_id = _bounded_text(envelope.get("owner_id"), field="owner_id", max_len=256)
        claim_class = _bounded_text(envelope.get("claim_class"), field="claim_class", max_len=64)
        if claim_class not in _ALLOWED_CLAIM_CLASSES:
            raise PromoGrantDecisionError("unsupported promo claim class")
        hardware_claim_id = _bounded_text(
            envelope.get("hardware_claim_id"),
            field="hardware_claim_id",
            max_len=512,
        )
        policy_version = _bounded_text(
            envelope.get("policy_version"),
            field="policy_version",
            max_len=128,
        )
        claim_id = _bounded_text(envelope.get("claim_id"), field="claim_id", max_len=512)
        expected_claim_id = promo_claim_id(
            owner_id=owner_id,
            claim_class=claim_class,
            hardware_claim_id=hardware_claim_id,
            policy_version=policy_version,
        )
        if claim_id != expected_claim_id:
            raise PromoGrantDecisionError("promo decision claim_id is not canonical")

        return PromoGrantDecision(
            decision_id=_bounded_text(
                envelope.get("decision_id"), field="decision_id", max_len=256
            ),
            issued_at=issued_at,
            expires_at=expires_at,
            owner_id=owner_id,
            claim_id=claim_id,
            claim_class=claim_class,
            hardware_claim_id=hardware_claim_id,
            assurance_tier=_bounded_text(
                envelope.get("assurance_tier"), field="assurance_tier", max_len=64
            ),
            node_id=_bounded_text(envelope.get("node_id"), field="node_id", max_len=128),
            amount_micro_units=amount,
            policy_version=policy_version,
            evidence_digest=_bounded_text(
                envelope.get("evidence_digest"), field="evidence_digest", max_len=128
            ),
            key_id=key_id,
        )


class SignedPromoGrantApplier:
    """Apply verified private promo decisions exactly once across claim + ledger stores."""

    def __init__(
        self,
        *,
        owner_store: OwnerAccountStore,
        ledger: OwnerCreditLedger,
        verifier: PromoDecisionVerifier,
    ) -> None:
        self.owner_store = owner_store
        self.ledger = ledger
        self.verifier = verifier

    def apply(
        self,
        envelope: Mapping[str, Any],
        *,
        now: int | float | None = None,
    ) -> PromoGrantApplyResult:
        decision = self.verifier.verify(envelope, now=now)
        if self.owner_store.get_owner(decision.owner_id) is None:
            raise PromoGrantDecisionError("promo decision references an unknown owner")

        if decision.claim_class == GPU_CLAIM:
            provider_owner = self.owner_store.owner_for_provider_node(decision.node_id)
            if provider_owner != decision.owner_id:
                raise PromoGrantDecisionError(
                    "GPU promo decision node is not bound to the decision owner"
                )

        try:
            self.owner_store.bind_device(
                decision.owner_id,
                decision.hardware_claim_id,
                assurance_tier=decision.assurance_tier,
            )
        except OwnerAccountStoreError as exc:
            raise PromoGrantDecisionError(str(exc)) from exc

        existing = self.owner_store.promo_claim_for_owner(
            decision.owner_id,
            decision.claim_class,
        )
        if existing is not None:
            expected = (
                decision.claim_id,
                decision.hardware_claim_id,
                decision.amount_micro_units,
                decision.policy_version,
            )
            actual = (
                existing.claim_id,
                existing.hardware_claim_id,
                existing.amount_micro_units,
                existing.policy_version,
            )
            if actual != expected:
                raise PromoGrantDecisionError(
                    "promo claim class was already consumed by a different grant"
                )
            claim = existing
        else:
            try:
                claim = self.owner_store.record_promo_claim(
                    claim_id=decision.claim_id,
                    owner_id=decision.owner_id,
                    claim_class=decision.claim_class,
                    hardware_claim_id=decision.hardware_claim_id,
                    amount_micro_units=decision.amount_micro_units,
                    policy_version=decision.policy_version,
                )
            except OwnerAccountStoreError as exc:
                raise PromoGrantDecisionError(str(exc)) from exc

        ledger_status = "credited"
        try:
            self.ledger.grant_owner_promo_credits(
                owner_id=decision.owner_id,
                amount_micro_units=decision.amount_micro_units,
                grant_reference=decision.claim_id,
                policy_version=decision.policy_version,
            )
        except DuplicateEventError:
            ledger_status = "already_credited"

        return PromoGrantApplyResult(
            owner_id=decision.owner_id,
            claim_id=decision.claim_id,
            claim_class=decision.claim_class,
            amount_micro_units=decision.amount_micro_units,
            policy_version=decision.policy_version,
            ledger_status=ledger_status,
            claim=claim,
        )
