"""Durable, bounded fan-out/fan-in coordination for agent sub-sessions."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Sequence

from .leases import LeaseState, NodeLease, NodeLeaseStore
from .session import AgentSession, AgentSessionStore, AgentTurn, TurnStatus
from .subagents import SubagentContract, SubagentGate, SubagentResult


class MultiAgentError(RuntimeError):
    """Base error for bounded subagent coordination."""


class DelegationDenied(MultiAgentError):
    """Raised when a fan-out, depth or step budget would be exceeded."""


@dataclass(frozen=True)
class SubagentExecution:
    contract: SubagentContract
    session: AgentSession
    turn: AgentTurn
    result: SubagentResult
    lease: NodeLease | None = None


@dataclass(frozen=True)
class SubagentBatch:
    parent_session_id: str
    parent_turn_id: str
    executions: tuple[SubagentExecution, ...]

    @property
    def completed(self) -> tuple[SubagentExecution, ...]:
        return tuple(item for item in self.executions if item.result.status == "COMPLETED")

    @property
    def failed(self) -> tuple[SubagentExecution, ...]:
        return tuple(item for item in self.executions if item.result.status != "COMPLETED")


Runner = Callable[[SubagentContract, AgentSession, AgentTurn], SubagentResult]
LeaseFactory = Callable[[SubagentContract, AgentSession, AgentTurn], NodeLease]


class SubagentCoordinator:
    """Create and execute child sessions without allowing recursive runaway work."""

    def __init__(
        self,
        session_store: AgentSessionStore,
        *,
        workspace_root: str = ".",
        max_children: int = 8,
        max_depth: int = 2,
        max_total_steps: int = 100,
        lease_store: NodeLeaseStore | None = None,
        lease_factory: LeaseFactory | None = None,
    ) -> None:
        if not 1 <= int(max_children) <= 64:
            raise ValueError("max_children must be between 1 and 64")
        if not 0 <= int(max_depth) <= 16:
            raise ValueError("max_depth must be between 0 and 16")
        if not 1 <= int(max_total_steps) <= 10000:
            raise ValueError("max_total_steps must be between 1 and 10000")
        self.session_store = session_store
        self.gate = SubagentGate(workspace_root)
        self.max_children = int(max_children)
        self.max_depth = int(max_depth)
        self.max_total_steps = int(max_total_steps)
        if (lease_store is None) != (lease_factory is None):
            raise ValueError("lease_store and lease_factory must be provided together")
        self.lease_store = lease_store
        self.lease_factory = lease_factory

    def _parent_depth(self, parent_session: AgentSession) -> int:
        try:
            return max(0, int(parent_session.state.get("subagent_depth", 0)))
        except (AttributeError, TypeError, ValueError):
            return 0

    def _validate_batch(self, parent_session: AgentSession, contracts: Sequence[SubagentContract]) -> None:
        if not contracts:
            raise ValueError("at least one subagent contract is required")
        if len(contracts) > self.max_children:
            raise DelegationDenied("subagent fan-out limit exceeded")
        depth = self._parent_depth(parent_session)
        if depth >= self.max_depth:
            raise DelegationDenied("subagent nesting limit exceeded")
        if sum(int(contract.max_steps) for contract in contracts) > self.max_total_steps:
            raise DelegationDenied("subagent step budget exceeded")

    def _create_child(
        self,
        parent_session: AgentSession,
        parent_turn_id: str,
        contract: SubagentContract,
    ) -> tuple[AgentSession, AgentTurn]:
        child_session = self.session_store.create_session(
            f"subagent:{contract.contract_id}",
            agent_version="1",
            principal_id=parent_session.principal_id,
            environment_type=parent_session.environment_type,
            state={
                "parent_session_id": parent_session.session_id,
                "parent_turn_id": parent_turn_id,
                "contract": contract.to_dict(),
                "subagent_depth": self._parent_depth(parent_session) + 1,
                "tenant_id": str((parent_session.state or {}).get("tenant_id") or ""),
            },
        )
        child_turn = self.session_store.start_turn(
            child_session.session_id,
            {"role": "user", "content": contract.task},
        )
        self.session_store.record_event(
            parent_session.session_id,
            "subagent.started",
            {
                "child_session_id": child_session.session_id,
                "child_turn_id": child_turn.turn_id,
                "contract_id": contract.contract_id,
                "depth": self._parent_depth(parent_session) + 1,
            },
            turn_id=parent_turn_id,
        )
        child_turn = self.session_store.transition_turn(child_turn.turn_id, TurnStatus.RUNNING, reason="subagent_started")
        return child_session, child_turn

    def _run_one(
        self,
        parent_session: AgentSession,
        parent_turn_id: str,
        contract: SubagentContract,
        runner: Runner,
    ) -> SubagentExecution:
        child_session, child_turn = self._create_child(parent_session, parent_turn_id, contract)
        lease: NodeLease | None = None
        result: SubagentResult
        failure: BaseException | None = None
        try:
            if self.lease_factory is not None:
                candidate_lease = self.lease_factory(contract, child_session, child_turn)
                if not isinstance(candidate_lease, NodeLease):
                    raise TypeError("subagent lease_factory must return NodeLease")
                if candidate_lease.status is not LeaseState.ACTIVE:
                    raise MultiAgentError("subagent lease is not active")
                if candidate_lease.session_id != child_session.session_id or candidate_lease.turn_id != child_turn.turn_id:
                    raise MultiAgentError("subagent lease is not bound to the child session and turn")
                # Do not release a foreign lease if a faulty factory returns
                # one for another session or turn.
                lease = candidate_lease
                self.session_store.record_event(
                    child_session.session_id,
                    "subagent.lease.bound",
                    {"lease_id": lease.lease_id, "node_id": lease.node_id, "model_id": lease.model_id},
                    turn_id=child_turn.turn_id,
                )
            result = runner(contract, child_session, child_turn)
            if not isinstance(result, SubagentResult):
                raise TypeError("subagent runner must return SubagentResult")
            self.gate.validate_result(contract, result)
            self.gate.validate_result_paths(contract, result)
        except Exception as exc:
            failure = exc
            result = SubagentResult(
                contract.contract_id,
                "FAILED",
                None,
                0,
                (),
                (),
                (f"{type(exc).__name__}: {exc}",),
            )
        finally:
            if lease is not None and self.lease_store is not None:
                try:
                    lease = self.lease_store.release(
                        lease.lease_id,
                        reason=(
                            "subagent_completed"
                            if failure is None and result.status == "COMPLETED"
                            else "subagent_failed"
                        ),
                    )
                    self.session_store.record_event(
                        child_session.session_id,
                        "subagent.lease.released",
                        {"lease_id": lease.lease_id, "status": lease.status.value},
                        turn_id=child_turn.turn_id,
                    )
                except Exception as exc:
                    # A successful model result is not allowed to hide a
                    # resource-release failure. The child remains failed and
                    # the exact error is represented in its durable result.
                    failure = failure or exc
                    result = SubagentResult(
                        contract.contract_id,
                        "FAILED",
                        None,
                        result.steps_used if "result" in locals() else 0,
                        (),
                        (),
                        tuple(result.errors if "result" in locals() else ())
                        + (f"{type(exc).__name__}: lease release failed",),
                    )
                    self.session_store.record_event(
                        child_session.session_id,
                        "subagent.lease.release_failed",
                        {"lease_id": lease.lease_id, "error_type": type(exc).__name__},
                        turn_id=child_turn.turn_id,
                    )
        self.session_store.record_item(
            child_session.session_id,
            child_turn.turn_id,
            "subagent_result",
            {"status": result.status, "output": result.output, "errors": list(result.errors)},
        )
        target = TurnStatus.COMPLETED if result.status == "COMPLETED" else TurnStatus.FAILED
        child_turn = self.session_store.transition_turn(
            child_turn.turn_id,
            target,
            error="; ".join(result.errors),
            reason="subagent_result" if failure is None else "subagent_exception",
        )
        if failure is not None:
            self.session_store.record_event(
                child_session.session_id,
                "subagent.failed",
                {"contract_id": contract.contract_id, "error_type": type(failure).__name__},
                turn_id=child_turn.turn_id,
            )
        child_session = self.session_store.get_session(child_session.session_id)
        execution = SubagentExecution(contract, child_session, child_turn, result, lease)
        self.session_store.record_event(
            parent_session.session_id,
            "subagent.completed" if result.status == "COMPLETED" else "subagent.failed",
            {
                "child_session_id": child_session.session_id,
                "child_turn_id": child_turn.turn_id,
                "contract_id": contract.contract_id,
                "status": result.status,
                "steps_used": result.steps_used,
            },
            turn_id=parent_turn_id,
        )
        return execution

    def delegate(
        self,
        parent_session_id: str,
        parent_turn_id: str,
        contracts: Sequence[SubagentContract],
        runner: Runner,
        *,
        max_workers: int | None = None,
    ) -> SubagentBatch:
        parent_session = self.session_store.get_session(parent_session_id)
        parent_turn = self.session_store.get_turn(parent_turn_id)
        if parent_turn.session_id != parent_session_id:
            raise MultiAgentError("parent turn belongs to a different session")
        if parent_turn.status not in {TurnStatus.QUEUED, TurnStatus.RUNNING}:
            raise MultiAgentError(f"parent turn is not runnable: {parent_turn.status.value}")
        self._validate_batch(parent_session, contracts)
        if parent_turn.status is TurnStatus.QUEUED:
            parent_turn = self.session_store.transition_turn(parent_turn_id, TurnStatus.RUNNING, reason="subagent_dispatch")
        self.session_store.transition_turn(parent_turn_id, TurnStatus.WAITING_FOR_SUBAGENTS, reason="subagent_dispatch")
        executions: list[SubagentExecution] = []
        workers = max(1, min(len(contracts), int(max_workers or len(contracts))))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="computemesh-subagent") as executor:
            futures: list[Future[SubagentExecution]] = [
                executor.submit(self._run_one, parent_session, parent_turn_id, contract, runner)
                for contract in contracts
            ]
            for future in as_completed(futures):
                executions.append(future.result())
        executions.sort(key=lambda item: item.contract.contract_id)
        self.session_store.record_event(
            parent_session_id,
            "subagents.completed",
            {
                "count": len(executions),
                "completed": sum(item.result.status == "COMPLETED" for item in executions),
                "failed": sum(item.result.status != "COMPLETED" for item in executions),
                "child_session_ids": [item.session.session_id for item in executions],
            },
            turn_id=parent_turn_id,
        )
        self.session_store.transition_turn(parent_turn_id, TurnStatus.RUNNING, reason="subagent_fan_in")
        return SubagentBatch(parent_session_id, parent_turn_id, tuple(executions))
