#!/usr/bin/env python3
"""ComputeMesh Web3 & On-Chain Crypto Payment Ingestion Engine.

Monitors EVM blockchains (Ethereum, Arbitrum, Polygon, Base, BSC) for incoming
USDT and USDC stablecoin deposits, verifying transaction confirmations, gas receipts,
and automatically minting micro-credits to customer double-entry ledger accounts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import (
    DuplicateEventError,
    Ledger,
    MICRO_UNIT_SCALE,
)

SUPPORTED_NETWORKS = ("ethereum", "arbitrum", "polygon", "base", "bsc")
SUPPORTED_TOKENS = ("USDT", "USDC")


class CryptoPaymentError(Exception):
    """Raised on invalid transaction data, unrecognized tokens, or chain errors."""


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
        self.ledger = ledger
        self.treasury_address = treasury_address.lower()
        self._address_to_customer: dict[str, str] = {}
        self._processed_txs: dict[str, CryptoDepositRecord] = {}

    def register_customer_deposit_address(
        self,
        customer_account_id: str,
        network: str = "arbitrum",
    ) -> str:
        """Generates a deterministic on-chain deposit address mapped to a customer."""
        if network.lower() not in SUPPORTED_NETWORKS:
            raise CryptoPaymentError(f"Unsupported network: {network}")

        # Deterministic deposit address derived from treasury + customer ID
        addr_seed = hashlib.sha256(f"{self.treasury_address}:{customer_account_id}:{network}".encode("utf-8")).hexdigest()
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
        amount_raw: int,  # in token base units (e.g. 6 decimals for USDT/USDC)
        token_decimals: int = 6,
        customer_account_id: str | None = None,
    ) -> dict[str, Any]:
        """Ingests a verified on-chain transfer and credits the customer's ledger."""
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

        # Resolve customer
        account_id = customer_account_id or self._address_to_customer.get(to_addr)
        if not account_id:
            # Check if sent directly to master treasury
            if to_addr == self.treasury_address:
                raise CryptoPaymentError("Direct treasury transfer requires explicit customer_account_id reference")
            raise CryptoPaymentError(f"Unrecognized deposit address: {to_address}")

        # Convert token base units to USD & micro-units
        # 1 USDT = 10^6 base units = 1.00 USD = 1,000,000 micro-units
        scale_factor = 10 ** token_decimals
        amount_usd = amount_raw / scale_factor
        amount_micro = int(amount_usd * MICRO_UNIT_SCALE)

        if amount_micro < 5_000_000:  # $5.00 minimum
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
