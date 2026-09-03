"""Content-free admission, metering and settlement for protected inference.

This coordinator deliberately never receives prompt/output plaintext. It joins the
public confidential session contract, owner-credit escrow and TEE-signed usage
receipt into one fail-closed lifecycle. Provider placement/ownership policy is
injected so private ranking logic remains outside the public repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from protocol.confidential_metering import (
    ConfidentialUsageReceipt,
    verify_confidential_usage_receipt,
)
from protocol.confidential_request_contract import (
    ConfidentialRequestContractError,
    verify_committed_attestation_nonce,
)
from runtime.confidential.data_plane import ConfidentialDataPlaneResult
from runtime.confidential.session import (
    ConfidentialSessionBroker,
    ConfidentialSessionProvision,
    ConfidentialSessionRecord,
    SQLiteConfidentialSessionStore,
    _timestamp,
)
from services.billing.confidential_escrow import ConfidentialCreditSettlement
from services.billing.confidential_owner_ledger import PayoutCapableConfidentialOwnerLedger
from services.billing.ledger import BillingError
from services.billing.owner_job_accounting import (
    ProviderOwnerShare,
    OwnerJobQuote,
    quote_destinations,
    quote_owner_job,
)
from services.common.pricing import calculate_max_charge_micro, calculate_token_charge_micro


class ConfidentialCoordinatorError(RuntimeError):
    pass


class ProviderOwnerResolver(Protocol):
    def __call__(self, provider_node_id: str) -> str:
        """Return the durable beneficial owner for one provider node, or raise."""


@dataclass(frozen=True)
class ConfidentialAdmission:
    session: ConfidentialSessionRecord
    provision: ConfidentialSessionProvision
    max_quote: OwnerJobQuote


@dataclass(frozen=True)
class ConfidentialSettlement:
    session: ConfidentialSessionRecord
    receipt: ConfidentialUsageReceipt
    quote: OwnerJobQuote
    escrow: ConfidentialCreditSettlement


class ConfidentialInferenceCoordinator:
    """Fail-closed financial/evidence lifecycle around opaque protected content."""

    def __init__(
        self,
        *,
        ledger: PayoutCapableConfidentialOwnerLedger,
        session_store: SQLiteConfidentialSessionStore,
        broker: ConfidentialSessionBroker,
        provider_owner_resolver: ProviderOwnerResolver,
        marketplace_fee_bps: int = 2500,
        self_compute_fee_bps: int = 1000,
    ) -> None:
        if not 0 <= marketplace_fee_bps <= 10_000:
            raise ValueError("marketplace_fee_bps must be between 0 and 10000")
        if not 1 <= self_compute_fee_bps <= 10_000:
            # Product invariant: even fully self-owned protected compute incurs a
            # non-zero infrastructure fee; zero would bypass Inetconnector billing.
            raise ValueError("self_compute_fee_bps must be between 1 and 10000")
        self.ledger = ledger
        self.session_store = session_store
        self.broker = broker
        self.provider_owner_resolver = provider_owner_resolver
        self.marketplace_fee_bps = marketplace_fee_bps
        self.self_compute_fee_bps = self_compute_fee_bps

    def _provider_owner(self, node_id: str) -> str:
        owner = str(self.provider_owner_resolver(node_id) or "").strip()
        if not owner:
            raise ConfidentialCoordinatorError("confidential provider owner is unresolved")
        return owner

    def _quote(
        self,
        *,
        customer_owner_id: str,
        provider_node_id: str,
        gross_micro_units: int,
    ) -> OwnerJobQuote:
        provider_owner = self._provider_owner(provider_node_id)
        return quote_owner_job(
            customer_owner_id=customer_owner_id,
            gross_reference_micro_units=gross_micro_units,
            provider_shares=(
                ProviderOwnerShare(
                    provider_node_id=provider_node_id,
                    owner_id=provider_owner,
                    ratio=1.0,
                ),
            ),
            marketplace_fee_bps=self.marketplace_fee_bps,
            self_compute_fee_bps=self.self_compute_fee_bps,
        )

    def open_session(
        self,
        *,
        account_id: str,
        model_id: str,
        privacy_class: str,
        operation: str,
        max_prompt_tokens: int,
        max_completion_tokens: int,
    ) -> ConfidentialAdmission:
        """Provision a protected runtime and reserve credits before any prompt exists."""
        provision = self.broker.provision(
            account_id=account_id,
            model_id=model_id,
            privacy_class=privacy_class,
            operation=operation,
            max_prompt_tokens=max_prompt_tokens,
            max_completion_tokens=max_completion_tokens,
        )
        provision.validate()
        if provision.account_id != account_id or provision.model_id != model_id:
            raise ConfidentialCoordinatorError("confidential broker changed account or model")
        if provision.privacy_class != privacy_class or provision.operation != operation:
            raise ConfidentialCoordinatorError("confidential broker changed privacy class or operation")
        if provision.max_prompt_tokens != max_prompt_tokens:
            raise ConfidentialCoordinatorError("confidential broker changed prompt token reservation")
        if provision.max_completion_tokens != max_completion_tokens:
            raise ConfidentialCoordinatorError("confidential broker changed completion token reservation")
        try:
            verify_committed_attestation_nonce(
                provision.endpoint.attestation_nonce,
                model_id=model_id,
                max_prompt_tokens=max_prompt_tokens,
                max_completion_tokens=max_completion_tokens,
            )
        except ConfidentialRequestContractError as exc:
            raise ConfidentialCoordinatorError(
                "confidential broker returned an unbound request contract"
            ) from exc

        max_gross = calculate_max_charge_micro(
            model_id,
            max_prompt_tokens,
            max_completion_tokens,
        )
        max_quote = self._quote(
            customer_owner_id=account_id,
            provider_node_id=provision.endpoint.node_id,
            gross_micro_units=max_gross,
        )
        if max_quote.customer_charge_micro_units <= 0:
            raise ConfidentialCoordinatorError("protected job must have a non-zero pre-authorized charge")

        # The session row is content-free. If a process dies after this write but
        # before reservation, dispatch still fails because the reservation is
        # independently required by settle/recovery. The OPEN row can expire.
        session = self.session_store.create(provision, hold_id=provision.job_id)
        try:
            self.ledger.reserve_confidential_credits(
                owner_id=account_id,
                reservation_id=provision.job_id,
                amount_micro_units=max_quote.customer_charge_micro_units,
            )
        except Exception:
            try:
                self.session_store.finish(job_id=provision.job_id, target="FAILED")
            except Exception:
                pass
            raise
        return ConfidentialAdmission(session=session, provision=provision, max_quote=max_quote)

    def verify_and_record_metering(
        self,
        *,
        session: ConfidentialSessionRecord,
        data_plane_result: ConfidentialDataPlaneResult,
    ) -> ConfidentialUsageReceipt:
        """Verify the TEE receipt and durably checkpoint `METERED` before billing."""
        if session.state != "DISPATCHED" or not session.envelope_id:
            raise ConfidentialCoordinatorError("confidential session is not awaiting metering")
        receipt = verify_confidential_usage_receipt(
            data_plane_result.usage_receipt,
            attested_metering_public_key=session.metering_public_key,
            expected_account_id=session.account_id,
            expected_job_id=session.job_id,
            expected_request_envelope_id=session.envelope_id,
            expected_response_id=data_plane_result.response.response_id,
            expected_node_id=session.node_id,
            expected_runtime_digest=session.runtime_digest,
            expected_privacy_class=session.privacy_class,
            expected_operation=session.operation,
            expected_model_id=session.model_id,
            max_prompt_tokens=session.max_prompt_tokens,
            max_completion_tokens=session.max_completion_tokens,
            not_after=_timestamp(session.expires_at),
        )
        if data_plane_result.response.binding.account_id != session.account_id:
            raise ConfidentialCoordinatorError("confidential response account binding mismatch")
        if data_plane_result.response.binding.job_id != session.job_id:
            raise ConfidentialCoordinatorError("confidential response job binding mismatch")
        self.session_store.record_metering(job_id=session.job_id, receipt=receipt)
        return receipt

    def settle_metered_session(self, *, job_id: str) -> ConfidentialSettlement:
        """Idempotently settle one durable TEE receipt into the owner-credit journal."""
        session = self.session_store.get(job_id)
        if session is None or session.state not in {"METERED", "COMPLETED"}:
            raise ConfidentialCoordinatorError("confidential session is not metered")
        receipt = session.usage_receipt
        if receipt is None:
            raise ConfidentialCoordinatorError("metered confidential session has no receipt")
        # Verify the stored receipt again before every recovery settlement; SQLite
        # persistence is not a substitute for the attested Ed25519 signature.
        receipt = verify_confidential_usage_receipt(
            receipt,
            attested_metering_public_key=session.metering_public_key,
            expected_account_id=session.account_id,
            expected_job_id=session.job_id,
            expected_request_envelope_id=session.envelope_id or "",
            expected_response_id=receipt.response_id,
            expected_node_id=session.node_id,
            expected_runtime_digest=session.runtime_digest,
            expected_privacy_class=session.privacy_class,
            expected_operation=session.operation,
            expected_model_id=session.model_id,
            max_prompt_tokens=session.max_prompt_tokens,
            max_completion_tokens=session.max_completion_tokens,
            not_after=_timestamp(session.expires_at),
        )
        gross = calculate_token_charge_micro(
            model_id=session.model_id,
            prompt_tokens=receipt.prompt_tokens,
            completion_tokens=receipt.completion_tokens,
        )
        quote = self._quote(
            customer_owner_id=session.account_id,
            provider_node_id=session.node_id,
            gross_micro_units=gross,
        )
        if quote.customer_charge_micro_units <= 0:
            raise ConfidentialCoordinatorError("protected metered job produced zero customer charge")
        try:
            escrow = self.ledger.settle_confidential_reservation(
                owner_id=session.account_id,
                reservation_id=session.hold_id,
                actual_amount_micro_units=quote.customer_charge_micro_units,
                destinations=quote_destinations(quote),
            )
        except BillingError as exc:
            raise ConfidentialCoordinatorError("confidential financial settlement failed") from exc
        if session.state == "METERED":
            session = self.session_store.finish(job_id=session.job_id, target="COMPLETED")
        return ConfidentialSettlement(session=session, receipt=receipt, quote=quote, escrow=escrow)

    def reconcile_metered(self, *, limit: int = 100) -> tuple[ConfidentialSettlement, ...]:
        """Recover compute-finished jobs after gateway restart without content access."""
        results: list[ConfidentialSettlement] = []
        for session in self.session_store.list_metered(limit=limit):
            results.append(self.settle_metered_session(job_id=session.job_id))
        return tuple(results)
