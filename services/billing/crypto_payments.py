#!/usr/bin/env python3
"""Experimental ComputeMesh on-chain payment ingestion.

This module is retained for research/testing compatibility. It is deliberately disabled
when COMPUTEMESH_PRODUCTION_MODE=1; commercial production customer funding must use the
configured regulated payment-service-provider path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import DuplicateEventError, Ledger, MICRO_UNIT_SCALE

SUPPORTED_NETWORKS = ("ethereum", "arbitrum", "polygon", "base", "bsc")
SUPPORTED_TOKENS = ("USDT", "USDC")


class CryptoPaymentError(Exception):
    """Raised on invalid transaction data or when production policy forbids this path."""


@dataclass(frozen=True)
class CryptoDepositRecord:
    tx_hash: str
    network: str
    token: str
    from_address: str
    to_address: str
    amount_usd: float
    amount_micro_units: int
    customer_account_id: str
    confirmed_at: str


class CryptoPaymentService:
    def __init__(
        self,
        ledger: Ledger,
        treasury_address: str = "0x71a99C8D2F8b3A15b81a84511d7e26d0De42B12F",
    ) -> None:
        if os.environ.get("COMPUTEMESH_PRODUCTION_MODE", "").strip() == "1":
            raise CryptoPaymentError(
                "direct on-chain customer crediting is disabled in production; use the approved payment provider"
            )
        self.ledger = ledger
        self.treasury_address = treasury_address.lower()
        self._address_to_customer: dict[str, str] = {}
        self._processed_txs: dict[str, CryptoDepositRecord] = {}

    def register_customer_deposit_address(
        self,
        customer_account_id: str,
        network: str = "arbitrum",
    ) -> str:
        if network.lower() not in SUPPORTED_NETWORKS:
            raise CryptoPaymentError(f"Unsupported network: {network}")
        addr_seed = hashlib.sha256(
            f"{self.treasury_address}:{customer_account_id}:{network}".encode("utf-8")
        ).hexdigest()
        deposit_addr = "0x" + addr_seed[:40].lower()
        self._address_to_customer[deposit_addr] = customer_account_id
        return deposit_addr

    def process_confirmed_transaction(
        self,
        *,
        tx_hash: str,
        network: str,
        token: str,
        from_address: str,
        to_address: str,
        amount_raw: int,
        token_decimals: int = 6,
        customer_account_id: str | None = None,
    ) -> dict[str, Any]:
        net = network.lower()
        tok = token.upper()
        to_addr = to_address.lower()
        tx = tx_hash.lower()
        if net not in SUPPORTED_NETWORKS:
            raise CryptoPaymentError(f"Unsupported network: {net}")
        if tok not in SUPPORTED_TOKENS:
            raise CryptoPaymentError(f"Unsupported token: {tok}. Supported: {SUPPORTED_TOKENS}")
        if amount_raw <= 0:
            raise CryptoPaymentError("Deposit amount must be strictly positive")
        account_id = customer_account_id or self._address_to_customer.get(to_addr)
        if not account_id:
            if to_addr == self.treasury_address:
                raise CryptoPaymentError("Direct treasury transfer requires explicit customer_account_id reference")
            raise CryptoPaymentError(f"Unrecognized deposit address: {to_address}")
        scale_factor = 10**token_decimals
        amount_usd = amount_raw / scale_factor
        amount_micro = int(amount_usd * MICRO_UNIT_SCALE)
        if amount_micro < 5_000_000:
            raise CryptoPaymentError("Minimum on-chain crypto deposit is $5.00")
        now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            journal_tx = self.ledger.deposit_customer_credits(
                customer_account_id=account_id,
                amount_micro_units=amount_micro,
                payment_reference=f"crypto:{net}:{tok}:{tx}",
            )
            record = CryptoDepositRecord(
                tx_hash=tx,
                network=net,
                token=tok,
                from_address=from_address,
                to_address=to_address,
                amount_usd=round(amount_usd, 4),
                amount_micro_units=amount_micro,
                customer_account_id=account_id,
                confirmed_at=now_str,
            )
            self._processed_txs[tx] = record
            return {
                "status": "credited",
                "transaction_id": journal_tx.tx_id,
                "tx_hash": tx,
                "network": net,
                "token": tok,
                "amount_usd": round(amount_usd, 2),
                "customer_account_id": account_id,
                "new_balance_usd": round(self.ledger.get_balance(account_id) / MICRO_UNIT_SCALE, 2),
            }
        except DuplicateEventError:
            return {
                "status": "already_processed",
                "tx_hash": tx,
                "customer_account_id": account_id,
            }
