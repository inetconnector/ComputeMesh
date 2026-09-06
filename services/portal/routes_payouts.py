"""ComputeMesh Fleet Portal Payouts & Stripe Connect Handler.

Handles owner earnings overview, Stripe Express onboarding generation, status refreshes,
and authenticated withdrawal settlements with double-entry ledger protection.
"""
from __future__ import annotations

from http import HTTPStatus
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.accounting import AccountingStore
from services.billing.ledger import Ledger, MICRO_UNIT_SCALE, MINIMUM_PAYOUT_MICRO_UNITS
from services.billing.owner_credits import owner_bucket_account
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.owner_settlement import OwnerPayoutProfile, OwnerPayoutProfileStore
from services.billing.owner_settlement_runtime import RobustOwnerSettlementExecutor
from services.billing.stripe_connect import StripeConnectService
from services.billing.stripe_integration import StripeIntegrationError


def _resolve_accounting_store() -> AccountingStore:
    path_env = os.environ.get("COMPUTEMESH_ACCOUNTING_DB_PATH") or os.environ.get("COMPUTEMESH_ACCOUNT_STORE_PATH")
    if path_env:
        return AccountingStore(storage_path=Path(path_env))
    if sys.platform == "win32":
        p = Path.home() / ".computemesh" / "accounting.db"
    else:
        p = Path("/var/lib/computemesh/accounting.db")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return AccountingStore(storage_path=p)


class PortalPayoutsHandler:
    """Manages Stripe Connect onboarding, payout profiles, and owner settlements for the portal."""

    def __init__(
        self,
        ledger: Ledger | None = None,
        account_store: AccountingStore | None = None,
        stripe_connect: StripeConnectService | None = None,
    ) -> None:
        self.account_store = account_store or _resolve_accounting_store()
        self.profile_store = OwnerPayoutProfileStore(self.account_store)
        self.ledger = ledger
        self.stripe_connect = stripe_connect or StripeConnectService(
            stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip()
        )
        self.settlement_executor = RobustOwnerSettlementExecutor(
            ledger=self.ledger,
            account_store=self.account_store,
            stripe_connect=self.stripe_connect,
        )

    def get_payout_overview(self, owner_id: str) -> dict[str, Any]:
        """Returns unified earnings balance, Stripe status, and payout history for an owner."""
        profile = self.profile_store.get_profile(owner_id)
        if not profile:
            profile = self.profile_store.upsert_profile(
                owner_id=owner_id,
                stripe_onboarding_status="not_started",
            )

        earned_account = owner_bucket_account(owner_id, "earned")
        balance_micro = 0
        if self.ledger:
            balance_micro = max(0, self.ledger.get_balance(earned_account))

        balance_usd = round(balance_micro / MICRO_UNIT_SCALE, 4)
        min_payout_usd = round(MINIMUM_PAYOUT_MICRO_UNITS / MICRO_UNIT_SCALE, 2)
        can_withdraw = profile.payouts_enabled and balance_micro >= MINIMUM_PAYOUT_MICRO_UNITS

        # Get recent settlement history
        settlements = self.account_store.list_settlements_for_owner(owner_id, limit=20)

        return {
            "owner_id": owner_id,
            "earned_balance_micro_units": balance_micro,
            "earned_balance_usd": balance_usd,
            "minimum_payout_usd": min_payout_usd,
            "can_withdraw": can_withdraw,
            "stripe_connected_account_id": profile.stripe_connected_account_id,
            "stripe_onboarding_status": profile.stripe_onboarding_status,
            "payouts_enabled": profile.payouts_enabled,
            "details_submitted": profile.details_submitted,
            "settlements": [s.to_dict() for s in settlements],
        }

    def start_onboarding(
        self,
        *,
        owner_id: str,
        email: str = "",
        country: str = "DE",
        refresh_url: str = "https://mesh.inetconnector.com/fleet?stripe=refresh",
        return_url: str = "https://mesh.inetconnector.com/fleet?stripe=return",
    ) -> dict[str, Any]:
        """Creates or retrieves a Stripe Connect Express account and returns the hosted KYC link."""
        profile = self.profile_store.get_profile(owner_id)
        account_id = profile.stripe_connected_account_id if profile else ""

        if not account_id:
            res = self.stripe_connect.create_connected_account(
                provider_node_id=owner_id,
                email=email,
                country=country,
            )
            account_id = res.stripe_connected_account_id
            self.profile_store.upsert_profile(
                owner_id=owner_id,
                stripe_connected_account_id=account_id,
                stripe_onboarding_status=res.onboarding_status,
                payouts_enabled=res.payouts_enabled,
                details_submitted=res.details_submitted,
            )

        link_res = self.stripe_connect.create_account_link(
            stripe_connected_account_id=account_id,
            refresh_url=refresh_url,
            return_url=return_url,
        )

        return {
            "owner_id": owner_id,
            "stripe_connected_account_id": account_id,
            "onboarding_url": link_res.onboarding_url,
            "expires_at": link_res.expires_at,
        }

    def refresh_status(self, owner_id: str) -> dict[str, Any]:
        """Refreshes live connected account capabilities directly from Stripe."""
        profile = self.profile_store.get_profile(owner_id)
        if not profile or not profile.stripe_connected_account_id:
            return self.get_payout_overview(owner_id)

        try:
            status_res = self.stripe_connect.retrieve_connected_account(
                provider_node_id=owner_id,
                stripe_connected_account_id=profile.stripe_connected_account_id,
            )
            self.profile_store.upsert_profile(
                owner_id=owner_id,
                stripe_connected_account_id=profile.stripe_connected_account_id,
                stripe_onboarding_status=status_res.onboarding_status,
                payouts_enabled=status_res.payouts_enabled,
                details_submitted=status_res.details_submitted,
            )
        except Exception:
            pass

        return self.get_payout_overview(owner_id)

    def execute_settlement(self, owner_id: str, amount_micro_units: int | None = None) -> dict[str, Any]:
        """Executes double-entry withdrawal settlement via Stripe Transfer."""
        profile = self.profile_store.get_profile(owner_id)
        if not profile or not profile.payouts_enabled:
            return {
                "error": "Stripe Connect onboarding must be completed before requesting payouts (payouts_enabled=False)."
            }

        earned_account = owner_bucket_account(owner_id, "earned")
        balance = self.ledger.get_balance(earned_account) if self.ledger else 0
        if balance < MINIMUM_PAYOUT_MICRO_UNITS:
            min_usd = round(MINIMUM_PAYOUT_MICRO_UNITS / MICRO_UNIT_SCALE, 2)
            cur_usd = round(balance / MICRO_UNIT_SCALE, 4)
            return {
                "error": f"Minimum payout threshold not reached. Current balance: ${cur_usd}, Minimum required: ${min_usd}."
            }

        rec = self.settlement_executor.run_owner_settlement(
            owner_id=owner_id,
            amount_micro_units=amount_micro_units,
        )
        return rec.to_dict()
