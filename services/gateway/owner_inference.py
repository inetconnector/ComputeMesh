"""Unified-owner inference engine.

This is the opt-in billing path for owner accounts. It preserves the public
``InferenceEngine`` response/streaming surface while replacing the legacy customer
and provider accounting inside ``create_metered_completion``.

Security/economic invariants:
- all non-teaser calls reserve owner spendable credits before execution;
- provider node ownership must resolve durably or the job fails closed;
- own-provider work is charged only the configured self-compute infrastructure fee;
- foreign-provider work uses normal marketplace economics;
- promo credit cannot fund foreign-provider payout by default;
- failed execution/settlement releases the owner hold and credits nobody.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any

from services.billing.ledger import BillingError, InsufficientBalanceError
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.owner_job_accounting import (
    ProviderOwnerShare,
    capture_owner_job_hold,
    quote_owner_job,
)
from services.common.config import CONFIG
from services.common.secure_memory import SecureMemoryBuffer
from services.gateway.catalog import (
    calculate_max_charge_micro,
    calculate_token_charge_micro,
    provider_shares_from_env,
    resolve_model_id,
)
from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import InferenceBackend
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.teaser import TeaserQuotaManager


class UnifiedOwnerInferenceEngine(InferenceEngine):
    """Inference engine that settles directly against unified owner balances."""

    def __init__(
        self,
        *,
        ledger: GatewayOwnerCreditLedger,
        owner_account_store: OwnerAccountStore,
        metrics: MetricsRegistry,
        teaser_manager: TeaserQuotaManager,
        backend: InferenceBackend | None = None,
        marketplace_fee_bps: int | None = None,
        self_compute_fee_bps: int | None = None,
        promo_foreign_cap_micro_units: int | None = None,
    ) -> None:
        super().__init__(
            ledger=ledger,
            metrics=metrics,
            teaser_manager=teaser_manager,
            backend=backend,
        )
        self.owner_ledger = ledger
        self.owner_account_store = owner_account_store
        self.marketplace_fee_bps = (
            int(os.environ.get("COMPUTEMESH_OPERATOR_FEE_BPS", "2500"))
            if marketplace_fee_bps is None
            else int(marketplace_fee_bps)
        )
        self.self_compute_fee_bps = (
            int(os.environ.get("COMPUTEMESH_SELF_COMPUTE_FEE_BPS", "1000"))
            if self_compute_fee_bps is None
            else int(self_compute_fee_bps)
        )
        self.promo_foreign_cap_micro_units = (
            int(os.environ.get("COMPUTEMESH_PROMO_FOREIGN_CAP_PER_JOB_MICRO_UNITS", "0"))
            if promo_foreign_cap_micro_units is None
            else int(promo_foreign_cap_micro_units)
        )
        if self.promo_foreign_cap_micro_units < 0:
            raise ValueError("promo foreign-provider cap must be non-negative")

    def _resolve_provider_owners(
        self,
        provider_shares: list[tuple[str, float]],
    ) -> tuple[ProviderOwnerShare, ...]:
        resolved: list[ProviderOwnerShare] = []
        for provider_node_id, ratio in provider_shares:
            owner_id = self.owner_account_store.owner_for_provider_node(provider_node_id)
            if not owner_id:
                raise BillingError(
                    f"provider node {provider_node_id!r} has no verified owner binding"
                )
            resolved.append(
                ProviderOwnerShare(
                    provider_node_id=provider_node_id,
                    owner_id=owner_id,
                    ratio=ratio,
                )
            )
        return tuple(resolved)

    def _enforce_promo_foreign_policy(
        self,
        *,
        hold,
        foreign_compute_gross_micro_units: int,
    ) -> None:
        """Ensure promo does not silently turn into withdrawable foreign earnings.

        The hold allocates earned -> purchased -> promo. Foreign-provider gross
        compute must therefore be covered by non-promo funds except for an explicit
        operator subsidy cap. Self-compute infrastructure fees may use promo.
        """
        nonpromo_reserved = sum(
            amount
            for bucket, amount in hold.allocations
            if bucket in {"earned", "purchased"}
        )
        required_nonpromo = max(
            0,
            foreign_compute_gross_micro_units - self.promo_foreign_cap_micro_units,
        )
        if nonpromo_reserved < required_nonpromo:
            raise InsufficientBalanceError(
                "Promo credits cannot fund this foreign-provider portion under the current policy; "
                f"required non-promo={required_nonpromo} µ$, reserved non-promo={nonpromo_reserved} µ$"
            )

    def create_metered_completion(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        client_ip: str = "127.0.0.1",
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        max_tokens: int | None = None,
    ) -> tuple[str, str, int, int, int]:
        # Public free teaser remains deliberately outside durable owner economics.
        if is_teaser:
            return super().create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                client_ip=client_ip,
                is_teaser=True,
                is_provider_self_compute=False,
                max_tokens=max_tokens,
            )

        owner_id = str(account_id or "").strip()
        if not owner_id:
            raise BillingError("owner account_id is required")

        canonical_model_id = resolve_model_id(model_id)
        requested_max = max_tokens or 512
        est_prompt_tokens = (
            sum(
                len(str(message.get("content", "")).split()) * 2
                for message in messages
                if isinstance(message, dict)
            )
            or 64
        )
        max_required_hold = calculate_max_charge_micro(
            canonical_model_id,
            est_prompt_tokens,
            requested_max,
        )
        hold = self.owner_ledger.create_owner_hold(
            owner_id=owner_id,
            amount_micro_units=max_required_hold,
            purpose=f"inference:{canonical_model_id}",
        )

        prompt_raw = json.dumps(messages)
        secure_buf = SecureMemoryBuffer(prompt_raw)
        try:
            try:
                with secure_buf.open_plaintext():
                    try:
                        backend_result = self.backend.complete(
                            model_id=canonical_model_id,
                            messages=messages,
                            max_tokens=requested_max,
                        )
                    except TypeError:
                        backend_result = self.backend.complete(
                            model_id=canonical_model_id,
                            messages=messages,
                        )
                completion_text = backend_result.text
                tokens_prompt = backend_result.prompt_tokens
                tokens_completion = backend_result.completion_tokens
            finally:
                secure_buf.zeroize()

            chat_id = f"chatcmpl-{secrets.token_hex(12)}"
            created_timestamp = int(time.time())
            provider_shares = (
                list(backend_result.provider_shares)
                if backend_result.provider_shares is not None
                else provider_shares_from_env()
            )
            resolved_shares = self._resolve_provider_owners(provider_shares)
            billing_job_id = backend_result.execution_job_id or chat_id
            gross_cost_micro = calculate_token_charge_micro(
                model_id=canonical_model_id,
                prompt_tokens=tokens_prompt,
                completion_tokens=tokens_completion,
            )
            quote = quote_owner_job(
                customer_owner_id=owner_id,
                gross_reference_micro_units=gross_cost_micro,
                provider_shares=resolved_shares,
                marketplace_fee_bps=self.marketplace_fee_bps,
                self_compute_fee_bps=self.self_compute_fee_bps,
            )
            self._enforce_promo_foreign_policy(
                hold=hold,
                foreign_compute_gross_micro_units=quote.foreign_compute_gross_micro_units,
            )
            capture_owner_job_hold(
                self.owner_ledger,
                hold=hold,
                quote=quote,
                job_id=billing_job_id,
            )

            self.metrics.record_request(
                model=canonical_model_id,
                prompt_tokens=tokens_prompt,
                completion_tokens=tokens_completion,
                cost_micro_units=quote.customer_charge_micro_units,
                status_code=200,
            )
            return (
                chat_id,
                completion_text,
                created_timestamp,
                tokens_prompt,
                tokens_completion,
            )
        except Exception:
            try:
                self.owner_ledger.release_owner_hold(hold.hold_id)
            except Exception:
                pass
            raise
