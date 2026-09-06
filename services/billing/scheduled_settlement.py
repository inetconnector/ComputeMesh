"""ComputeMesh Automated Scheduled Settlement Daemon & Batch Processor.

Periodically inspects all registered provider owners, identifies accounts with
active Stripe Connect payout readiness (payouts_enabled=True) and earned balances
meeting the minimum payout threshold ($25.00), and executes safe, idempotent Stripe Transfers.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.accounting import AccountingStore, SettlementRecord
from services.billing.ledger import Ledger, MICRO_UNIT_SCALE, MINIMUM_PAYOUT_MICRO_UNITS
from services.billing.owner_credits import owner_bucket_account
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.owner_settlement import OwnerPayoutProfileStore
from services.billing.owner_settlement_runtime import RobustOwnerSettlementExecutor
from services.billing.stripe_connect import StripeConnectService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ComputeMesh-Settlement] %(message)s",
)
logger = logging.getLogger("computemesh.settlement")


def run_batch_settlement_cycle(
    ledger: Ledger,
    account_store: AccountingStore,
    stripe_connect: StripeConnectService,
) -> list[dict[str, Any]]:
    """Runs a complete settlement inspection and payout cycle across all owners."""
    profile_store = OwnerPayoutProfileStore(account_store)
    settlement_executor = RobustOwnerSettlementExecutor(
        ledger=ledger,
        account_store=account_store,
        stripe_connect=stripe_connect,
    )

    results: list[dict[str, Any]] = []
    logger.info("Starting automated batch settlement cycle...")

    # Fetch all payout profiles with payouts_enabled=True
    profiles = profile_store.list_profiles(payouts_enabled_only=True) if hasattr(profile_store, "list_profiles") else []
    if not profiles:
        # Fallback to scanning database directly
        with profile_store._connection() as conn:
            cur = conn.execute("SELECT * FROM owner_payout_profiles WHERE payouts_enabled = 1")
            rows = cur.fetchall()
            from services.billing.owner_settlement import OwnerPayoutProfile
            profiles = [
                OwnerPayoutProfile(
                    owner_id=r["owner_id"],
                    stripe_connected_account_id=r["stripe_connected_account_id"],
                    stripe_onboarding_status=r["stripe_onboarding_status"],
                    payouts_enabled=bool(r["payouts_enabled"]),
                    details_submitted=bool(r["details_submitted"]),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

    logger.info(f"Found {len(profiles)} owner payout profile(s) with payouts_enabled=True.")

    for profile in profiles:
        if not profile.payouts_enabled:
            continue

        owner_id = profile.owner_id
        earned_account = owner_bucket_account(owner_id, "earned")
        balance = ledger.get_balance(earned_account)

        if balance < MINIMUM_PAYOUT_MICRO_UNITS:
            continue

        balance_usd = round(balance / MICRO_UNIT_SCALE, 4)
        logger.info(f"Eligible settlement found for owner '{owner_id}': ${balance_usd} USD ({balance} micro-units).")

        try:
            record = settlement_executor.run_owner_settlement(owner_id=owner_id)
            logger.info(f"✓ Settlement '{record.settlement_id}' completed for owner '{owner_id}': Status={record.status}, TransferID={record.stripe_transfer_id}")
            results.append(record.to_dict())
        except Exception as exc:
            logger.error(f"⚠️ Settlement failed for owner '{owner_id}': {exc}")
            results.append({"owner_id": owner_id, "error": str(exc), "status": "failed"})

    logger.info(f"Settlement cycle finished. Processed {len(results)} settlement(s).")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Automated Settlement Processor")
    parser.add_argument("--daemon", action="store_true", help="Run continuously as background daemon")
    parser.add_argument("--interval", type=int, default=3600, help="Check interval in seconds for daemon mode (default: 3600s / 1h)")
    parser.add_argument("--ledger-path", type=str, default="", help="Path to gateway_ledger.json")
    parser.add_argument("--db-path", type=str, default="", help="Path to accounting.db")
    args = parser.parse_args()

    ledger_path_str = args.ledger_path or os.environ.get("COMPUTEMESH_GATEWAY_LEDGER_PATH")
    if not ledger_path_str:
        ledger_path = Path.home() / ".computemesh" / "gateway_ledger.json" if sys.platform == "win32" else Path("/var/lib/computemesh/gateway_ledger.json")
    else:
        ledger_path = Path(ledger_path_str)

    db_path_str = args.db_path or os.environ.get("COMPUTEMESH_ACCOUNTING_DB_PATH") or os.environ.get("COMPUTEMESH_ACCOUNT_STORE_PATH")
    if not db_path_str:
        db_path = Path.home() / ".computemesh" / "accounting.db" if sys.platform == "win32" else Path("/var/lib/computemesh/accounting.db")
    else:
        db_path = Path(db_path_str)

    ledger = GatewayOwnerCreditLedger(storage_path=ledger_path)
    account_store = AccountingStore(storage_path=db_path)
    stripe_connect = StripeConnectService(stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip())

    if args.daemon:
        logger.info(f"ComputeMesh Settlement Daemon starting with interval {args.interval}s...")
        while True:
            try:
                run_batch_settlement_cycle(ledger, account_store, stripe_connect)
            except Exception as exc:
                logger.error(f"Unexpected error in settlement daemon: {exc}")
            time.sleep(args.interval)
    else:
        run_batch_settlement_cycle(ledger, account_store, stripe_connect)

    return 0


if __name__ == "__main__":
    sys.exit(main())
