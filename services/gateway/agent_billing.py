"""Opt-in billing bridge for durable gateway agent turns.

The public agent worker remains provider-neutral. This adapter is owned by the
gateway deployment and reuses the existing hold/capture ledger so agent turns
cannot silently create a second accounting system. It stores only the minimum
private execution evidence needed to settle one deterministic turn journal.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.billing.ledger import BillingError, Ledger
from services.common.pricing import calculate_max_charge_micro, calculate_token_charge_micro


class AgentBillingError(BillingError):
    """Raised when an agent turn cannot be settled from verified execution data."""


@dataclass(frozen=True)
class AgentBillingReservation:
    hold_id: str
    account_id: str
    model_id: str
    turn_id: str


@dataclass(frozen=True)
class _ObservedExecution:
    job_id: str
    prompt_tokens: int
    completion_tokens: int
    provider_shares: tuple[tuple[str, float], ...]


class AgentBillingEvidenceStore:
    """Private SQLite store for verified per-turn execution evidence.

    Provider shares are deliberately kept out of the public session database,
    usage events and traces. The store is optional so test/dev deployments that
    use an in-memory ledger retain the previous behavior.
    """

    def __init__(self, path: str | Path) -> None:
        if str(path) == ":memory:":
            raise ValueError("billing evidence requires a filesystem database")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30.0)
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS agent_billing_evidence (
                turn_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                provider_shares_json TEXT NOT NULL,
                observed_at REAL NOT NULL,
                PRIMARY KEY(turn_id, job_id)
            )"""
        )
        self._connection.commit()

    @staticmethod
    def _decode(row: sqlite3.Row | tuple[Any, ...]) -> _ObservedExecution:
        raw_shares = json.loads(str(row[5]))
        return _ObservedExecution(
            job_id=str(row[1]),
            prompt_tokens=int(row[3]),
            completion_tokens=int(row[4]),
            provider_shares=tuple((str(provider), float(ratio)) for provider, ratio in raw_shares),
        )

    def record(self, turn_id: str, model_id: str, evidence: _ObservedExecution) -> None:
        with self._lock:
            row = self._connection.execute(
                """SELECT turn_id, job_id, model_id, prompt_tokens, completion_tokens,
                          provider_shares_json, observed_at
                   FROM agent_billing_evidence WHERE turn_id = ? AND job_id = ?""",
                (str(turn_id), evidence.job_id),
            ).fetchone()
            if row is not None:
                existing = self._decode(row)
                if existing != evidence or str(row[2]) != str(model_id):
                    raise AgentBillingError("durable execution evidence conflicts with a prior observation")
                return
            self._connection.execute(
                """INSERT INTO agent_billing_evidence(
                    turn_id, job_id, model_id, prompt_tokens, completion_tokens,
                    provider_shares_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))""",
                (
                    str(turn_id),
                    evidence.job_id,
                    str(model_id),
                    evidence.prompt_tokens,
                    evidence.completion_tokens,
                    json.dumps(list(evidence.provider_shares), ensure_ascii=False, separators=(",", ":")),
                ),
            )
            self._connection.commit()

    def list_for_turn(self, turn_id: str, model_id: str) -> tuple[_ObservedExecution, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT turn_id, job_id, model_id, prompt_tokens, completion_tokens,
                          provider_shares_json, observed_at
                   FROM agent_billing_evidence
                   WHERE turn_id = ? AND model_id = ? ORDER BY job_id""",
                (str(turn_id), str(model_id)),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def clear_turn(self, turn_id: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM agent_billing_evidence WHERE turn_id = ?", (str(turn_id),))
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _bounded_id(value: Any, *, field: str, maximum: int = 160) -> str:
    clean = str(value or "").strip()
    if not 1 <= len(clean) <= maximum:
        raise AgentBillingError(f"{field} is required and bounded")
    return clean


class GatewayAgentBilling:
    """Reserve and settle one durable agent turn against the gateway ledger."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        model_id: str,
        max_tokens: int,
        max_iterations: int,
        prompt_reserve_tokens: int | None = None,
        hold_ttl_seconds: float = 900.0,
        evidence_store: AgentBillingEvidenceStore | None = None,
    ) -> None:
        required_methods = ("create_hold", "get_hold", "renew_hold", "release_hold", "capture_hold")
        if any(not callable(getattr(ledger, method, None)) for method in required_methods):
            raise TypeError("ledger must provide the existing credit hold/capture contract")
        self.ledger = ledger
        self.model_id = _bounded_id(model_id, field="model_id", maximum=256)
        self.max_tokens = max(1, min(int(max_tokens), 131_072))
        self.max_iterations = max(1, min(int(max_iterations), 20))
        self.prompt_reserve_tokens = max(
            1,
            min(
                int(prompt_reserve_tokens if prompt_reserve_tokens is not None else self.max_tokens),
                1_000_000,
            ),
        )
        self.hold_ttl_seconds = max(1.0, min(float(hold_ttl_seconds), 86_400.0))
        self.evidence_store = evidence_store
        self._turn_id = ""
        self._observed: dict[str, _ObservedExecution] = {}

    @property
    def _maximum_reserve_micro_units(self) -> int:
        return calculate_max_charge_micro(
            self.model_id,
            self.prompt_reserve_tokens * self.max_iterations,
            self.max_tokens * self.max_iterations,
        )

    def _clear_evidence(self, turn_id: str) -> None:
        if self.evidence_store is not None:
            try:
                self.evidence_store.clear_turn(turn_id)
            except Exception:
                # Financial settlement is authoritative; cleanup must not turn
                # a captured hold into a worker failure.
                pass

    def observe(self, result: Any) -> None:
        """Capture private, verified backend evidence before public conversion."""
        job_id = getattr(result, "execution_job_id", None)
        if not job_id:
            return
        job_id = _bounded_id(job_id, field="execution_job_id")
        prompt_tokens = getattr(result, "prompt_tokens", None)
        completion_tokens = getattr(result, "completion_tokens", None)
        if (
            isinstance(prompt_tokens, bool)
            or not isinstance(prompt_tokens, int)
            or prompt_tokens < 0
            or isinstance(completion_tokens, bool)
            or not isinstance(completion_tokens, int)
            or completion_tokens < 0
        ):
            raise AgentBillingError("execution returned invalid token usage")
        raw_shares = getattr(result, "provider_shares", None)
        if not isinstance(raw_shares, (list, tuple)) or not raw_shares:
            raise AgentBillingError("execution is missing verified provider shares")
        shares: list[tuple[str, float]] = []
        for raw_provider, raw_ratio in raw_shares:
            provider = _bounded_id(raw_provider, field="provider_node_id")
            ratio = float(raw_ratio)
            if not math.isfinite(ratio) or ratio <= 0:
                raise AgentBillingError("execution contains invalid provider shares")
            shares.append((provider, ratio))
        observed = _ObservedExecution(job_id, prompt_tokens, completion_tokens, tuple(shares))
        previous = self._observed.get(job_id)
        if previous is not None and previous != observed:
            raise AgentBillingError("execution job was observed with conflicting evidence")
        self._observed[job_id] = observed
        if self.evidence_store is not None and self._turn_id:
            self.evidence_store.record(self._turn_id, self.model_id, observed)

    def reserve(self, session: Any, turn: Any) -> AgentBillingReservation:
        account_id = _bounded_id(getattr(session, "principal_id", ""), field="principal_id")
        turn_id = _bounded_id(getattr(turn, "turn_id", ""), field="turn_id")
        self._turn_id = turn_id
        self._observed = {
            evidence.job_id: evidence
            for evidence in (
                self.evidence_store.list_for_turn(turn_id, self.model_id)
                if self.evidence_store is not None
                else ()
            )
        }
        hold_id = f"agent_turn:{turn_id}"
        existing = self.ledger.get_hold(hold_id)
        if existing is not None:
            if existing.account_id != account_id or existing.model_id != self.model_id:
                raise AgentBillingError("agent turn billing hold does not match its owner or model")
            if existing.status == "captured":
                self._clear_evidence(turn_id)
                return AgentBillingReservation(hold_id, account_id, self.model_id, turn_id)
            if existing.status == "active" and self.ledger.renew_hold(hold_id, self.hold_ttl_seconds):
                return AgentBillingReservation(hold_id, account_id, self.model_id, turn_id)
        self.ledger.create_hold(
            account_id=account_id,
            amount_micro_units=self._maximum_reserve_micro_units,
            model_id=self.model_id,
            ttl_seconds=self.hold_ttl_seconds,
            hold_id=hold_id,
        )
        return AgentBillingReservation(hold_id, account_id, self.model_id, turn_id)

    def settle(self, reservation: AgentBillingReservation, _run: Any) -> None:
        if not isinstance(reservation, AgentBillingReservation):
            raise AgentBillingError("invalid agent billing reservation")
        hold = self.ledger.get_hold(reservation.hold_id)
        if hold is None:
            raise AgentBillingError("agent billing hold disappeared")
        if hold.status == "captured":
            return
        if not self._observed:
            self.ledger.release_hold(reservation.hold_id)
            self._clear_evidence(reservation.turn_id)
            return
        prompt_tokens = sum(item.prompt_tokens for item in self._observed.values())
        completion_tokens = sum(item.completion_tokens for item in self._observed.values())
        weighted: dict[str, float] = {}
        for item in self._observed.values():
            charge = calculate_token_charge_micro(
                self.model_id,
                item.prompt_tokens,
                item.completion_tokens,
            )
            total_ratio = sum(ratio for _, ratio in item.provider_shares)
            if total_ratio <= 0:
                raise AgentBillingError("execution provider shares have no weight")
            for provider, ratio in item.provider_shares:
                weighted[provider] = weighted.get(provider, 0.0) + charge * (ratio / total_ratio)
        if not weighted:
            raise AgentBillingError("agent turn has no billable provider share")
        self.ledger.capture_hold(
            hold_id=reservation.hold_id,
            job_id=f"agent-turn:{reservation.turn_id}",
            customer_account_id=reservation.account_id,
            provider_shares=list(weighted.items()),
            model_id=reservation.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._clear_evidence(reservation.turn_id)

    def release(self, reservation: AgentBillingReservation | None, _error: BaseException) -> None:
        if isinstance(reservation, AgentBillingReservation):
            self.ledger.release_hold(reservation.hold_id)
            self._clear_evidence(reservation.turn_id)


__all__ = [
    "AgentBillingError",
    "AgentBillingEvidenceStore",
    "AgentBillingReservation",
    "GatewayAgentBilling",
]
