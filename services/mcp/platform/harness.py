"""Session-backed adapter around the existing ComputeMesh AgentLoop."""
from __future__ import annotations

import hashlib
import inspect
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ..agent_loop import (
    AgentApprovalRequired,
    AgentControlRequested,
    AgentExecutionResult,
    AgentLoop,
)
from .context import ContextBuild, ContextLimitError, ContextManager
from .contracts import RuntimePolicyEnvelope
from .multi_agent import Runner, SubagentBatch, SubagentCoordinator
from .session import AgentSession, AgentSessionStore, AgentTurn, ControlAction, TurnStatus
from .subagents import SubagentContract
from .tracing import TraceStore
from .usage import UsageBudget, UsageDelta, UsageLedger, UsageRecord


@dataclass(frozen=True)
class HarnessRun:
    session: AgentSession
    turn: AgentTurn
    execution: AgentExecutionResult
    context: ContextBuild
    usage_record: UsageRecord | None = None
    control_action: str | None = None


class MeshAgentHarness:
    """Durable lifecycle wrapper that leaves the legacy AgentLoop intact."""

    def __init__(
        self,
        session_store: AgentSessionStore,
        *,
        agent_loop: AgentLoop | None = None,
        context_manager: ContextManager | None = None,
        tool_broker: Any | None = None,
        tool_broker_factory: Callable[..., Any] | None = None,
        context_compactor: Callable[[Sequence[Mapping[str, Any]]], str] | None = None,
        usage_ledger: UsageLedger | None = None,
        subagent_coordinator: SubagentCoordinator | None = None,
        trace_store: TraceStore | None = None,
        approved_approval_ids: Sequence[str] = (),
        disabled_tools: Sequence[str] = (),
        runtime_policy: RuntimePolicyEnvelope | None = None,
        request_id: str | None = None,
    ) -> None:
        self.session_store = session_store
        self.agent_loop = agent_loop or AgentLoop()
        self.context_manager = context_manager or ContextManager()
        self.tool_broker = tool_broker
        self.tool_broker_factory = tool_broker_factory
        self.context_compactor = context_compactor
        self.usage_ledger = usage_ledger
        self.subagent_coordinator = subagent_coordinator
        self.trace_store = trace_store
        self.approved_approval_ids = tuple(str(value) for value in approved_approval_ids if str(value).strip())
        self.disabled_tools = tuple(str(value) for value in disabled_tools if str(value).strip())
        self.runtime_policy = runtime_policy
        self.request_id = str(request_id or "").strip() or None

    def delegate_subagents(
        self,
        session_id: str,
        turn_id: str,
        contracts: Sequence[SubagentContract],
        runner: Runner,
        *,
        max_workers: int | None = None,
    ) -> SubagentBatch:
        if self.subagent_coordinator is None:
            raise RuntimeError("subagent coordinator is unavailable")
        return self.subagent_coordinator.delegate(
            session_id,
            turn_id,
            contracts,
            runner,
            max_workers=max_workers,
        )

    @staticmethod
    def _safe_progress(event: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"event", "iteration", "max_iterations", "tool", "call_id"}
        return {str(key): value for key, value in event.items() if str(key) in allowed}

    @staticmethod
    def _safe_provenance(provenance: Mapping[str, Any] | None) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for field in ("execution_job_ids", "execution_node_ids"):
            values = provenance.get(field) if isinstance(provenance, Mapping) else None
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, (list, tuple, set, frozenset)):
                continue
            bounded: list[str] = []
            for value in values:
                if isinstance(value, str) and 1 <= len(value.strip()) <= 160:
                    value = value.strip()
                    if value not in bounded:
                        bounded.append(value)
                if len(bounded) >= 32:
                    break
            if bounded:
                result[field] = bounded
        return result

    def run_turn(
        self,
        session_id: str,
        turn_id: str,
        *,
        model: str,
        llm_caller: Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]],
        is_owner: bool = True,
        max_iterations: int | None = None,
        context_summary: str | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        principal_id: str = "",
        tenant_id: str = "",
        node_id: str = "",
        usage_budget: UsageBudget | None = None,
    ) -> HarnessRun:
        turn = self.session_store.get_turn(turn_id)
        if turn.session_id != str(session_id):
            raise ValueError("turn belongs to a different session")
        session = self.session_store.get_session(session_id)
        if self.runtime_policy is not None:
            session_principal = str(session.principal_id or "").strip()
            requested_principal = str(principal_id or "").strip()
            if session_principal and requested_principal and session_principal != requested_principal:
                policy_error: Exception = PermissionError("runtime policy principal binding mismatch")
            else:
                try:
                    self.runtime_policy.validate(
                        request_id=self.request_id or f"agent-turn:{turn_id}",
                        principal_id=requested_principal or session_principal or None,
                        fleet_id=self.runtime_policy.fleet_id or None,
                    )
                except Exception as exc:
                    policy_error = exc
                else:
                    policy_error = None
            if policy_error is not None:
                current = self.session_store.get_turn(turn_id)
                if current.status in {
                    TurnStatus.QUEUED,
                    TurnStatus.RUNNING,
                    TurnStatus.RESUMING,
                }:
                    try:
                        self.session_store.transition_turn(
                            turn_id,
                            TurnStatus.FAILED,
                            error="runtime policy rejected",
                            reason="runtime_policy_denied",
                        )
                    except Exception:
                        pass
                self.session_store.record_event(
                    session_id,
                    "runtime_policy.rejected",
                    {"turn_id": turn_id, "error_type": type(policy_error).__name__},
                    turn_id=turn_id,
                )
                raise PermissionError("runtime policy validation failed") from policy_error
        if turn.status is TurnStatus.QUEUED:
            turn = self.session_store.transition_turn(turn_id, TurnStatus.RUNNING)
        elif turn.status is TurnStatus.RESUMING:
            turn = self.session_store.transition_turn(turn_id, TurnStatus.RUNNING, reason="approval_resume")
        elif turn.status is not TurnStatus.RUNNING:
            raise ValueError(f"turn is not runnable: {turn.status.value}")

        items = self.session_store.list_items(session_id)
        checkpoint = session.state.get("checkpoint")
        checkpoint_summary = checkpoint.get("context_summary") if isinstance(checkpoint, Mapping) else None
        effective_summary = context_summary or (str(checkpoint_summary) if checkpoint_summary else None)
        try:
            context = self.context_manager.build(
                [item.content for item in items],
                summary=effective_summary,
            )
        except ContextLimitError:
            if self.context_compactor is None:
                self.session_store.record_event(session_id, "turn.failed", {"error_type": "ContextLimitError"}, turn_id=turn_id)
                self.session_store.transition_turn(turn_id, TurnStatus.FAILED, error="context exceeds budget")
                raise
            self.session_store.transition_turn(turn_id, TurnStatus.COMPACTING, reason="context_limit")
            self.session_store.record_event(session_id, "context.compaction.started", {"turn_id": turn_id, "item_count": len(items)}, turn_id=turn_id)
            try:
                compacted_summary = str(self.context_compactor([item.content for item in items]) or "").strip()
                if not compacted_summary:
                    raise ValueError("context compactor returned an empty summary")
                self.session_store.checkpoint(session_id, {"context_summary": compacted_summary, "source_item_count": len(items)})
                self.session_store.record_event(
                    session_id,
                    "context.compaction.completed",
                    {"turn_id": turn_id, "summary_digest": hashlib.sha256(compacted_summary.encode("utf-8")).hexdigest()},
                    turn_id=turn_id,
                )
                self.session_store.transition_turn(turn_id, TurnStatus.RUNNING, reason="context_compacted")
                context = self.context_manager.build([item.content for item in items], summary=compacted_summary)
            except Exception:
                self.session_store.transition_turn(turn_id, TurnStatus.FAILED, error="context compaction failed", reason="context_compaction_failed")
                raise
        except Exception as exc:
            self.session_store.record_event(
                session_id,
                "turn.failed",
                {"error_type": type(exc).__name__, "error": str(exc)},
                turn_id=turn_id,
            )
            self.session_store.transition_turn(turn_id, TurnStatus.FAILED, error=str(exc))
            raise
        self.session_store.record_event(
            session_id,
            "context.built",
            {
                "turn_id": turn_id,
                "estimated_tokens": context.estimated_tokens,
                "budget_tokens": context.budget_tokens,
                "compacted": context.compacted,
                "omitted_messages": context.omitted_messages,
                "source_digest": context.source_digest,
            },
            turn_id=turn_id,
        )

        resume_checkpoint = self.session_store.get_turn_checkpoint(turn_id)
        # Approval resumes intentionally replay the approved tool call through
        # the broker, which consumes the one-shot approval and executes its
        # side effect. Do not feed the pre-approval checkpoint back as if that
        # side effect had already completed.
        if resume_checkpoint is not None and self.approved_approval_ids:
            self.session_store.checkpoint_turn(turn_id, None)
            resume_checkpoint = None

        def progress(event: dict[str, Any]) -> None:
            safe = self._safe_progress(event)
            self.session_store.record_event(session_id, "turn.progress", safe, turn_id=turn_id)
            if self.trace_store is not None:
                try:
                    progress_span = self.trace_store.start(
                        session_id=str(session_id),
                        turn_id=str(turn_id),
                        kind="progress",
                        name=str(safe.get("event") or "agent.progress"),
                        trace_id=root_span.trace_id if root_span is not None else None,
                        parent_span_id=root_span.span_id if root_span is not None else None,
                        attributes={"iteration": safe.get("iteration"), "tool": safe.get("tool")},
                    )
                    self.trace_store.finish(progress_span.span_id)
                except Exception:
                    pass
            if on_progress:
                try:
                    on_progress(dict(event))
                except Exception:
                    pass

        root_span = None
        if self.trace_store is not None:
            try:
                root_span = self.trace_store.start(
                    session_id=str(session_id),
                    turn_id=str(turn_id),
                    kind="turn",
                    name="agent.turn",
                    attributes={"model": model},
                )
            except Exception:
                root_span = None

        def persist_execution_messages(execution: AgentExecutionResult) -> None:
            known_content = {
                (item.content.get("role"), str(item.content))
                for item in items
            }
            for message in execution.messages:
                role = str(message.get("role") or "")
                if role not in {"assistant", "tool"}:
                    continue
                key = (role, str(message))
                if key not in known_content:
                    self.session_store.record_item(session_id, turn_id, role, message)
                    known_content.add(key)

        def pending_control() -> str | None:
            control = self.session_store.get_pending_control(session_id, turn_id)
            return control.action.value if control is not None else None

        cancel_event = threading.Event()
        monitor_stop = threading.Event()

        def monitor_cancel() -> None:
            while not monitor_stop.wait(0.05):
                if pending_control() == ControlAction.CANCEL.value:
                    cancel_event.set()
                    return

        cancel_monitor = threading.Thread(target=monitor_cancel, name=f"agent-cancel-{turn_id}", daemon=True)
        cancel_monitor.start()

        def finish_control(execution: AgentExecutionResult, action: str) -> HarnessRun:
            persist_execution_messages(execution)
            provenance = self._safe_provenance(execution.provenance)
            try:
                self.session_store.apply_pending_control(session_id, turn_id, action)
            except Exception:
                # A concurrent API request or worker recovery may already have
                # resolved the control. The durable turn remains authoritative.
                pass
            if self.trace_store is not None and root_span is not None:
                try:
                    self.trace_store.finish(
                        root_span.span_id,
                        status=f"control_{action}",
                        attributes={
                            "execution_job_count": len(provenance.get("execution_job_ids", [])),
                            "execution_node_count": len(provenance.get("execution_node_ids", [])),
                            "execution_job_ids": provenance.get("execution_job_ids", []),
                            "execution_node_ids": provenance.get("execution_node_ids", []),
                        },
                    )
                except Exception:
                    pass
            return HarnessRun(
                self.session_store.get_session(session_id),
                self.session_store.get_turn(turn_id),
                execution,
                context,
                None,
                action,
            )

        try:

            tool_broker = (
                self.tool_broker_factory(session_id, turn_id, self.approved_approval_ids)
                if self.tool_broker_factory is not None
                else self.tool_broker
            )
            agent_loop_kwargs: dict[str, Any] = {
                "is_owner": is_owner,
                "max_iterations": max_iterations,
                "on_progress": progress,
                "tool_broker": tool_broker,
                "disabled_tools": list(self.disabled_tools),
                "should_stop": pending_control,
                "on_checkpoint": lambda checkpoint: self.session_store.checkpoint_turn(turn_id, checkpoint),
                "resume_state": resume_checkpoint,
                "cancel_event": cancel_event,
            }
            # Preserve compatibility with injected legacy loop adapters that
            # predate durable checkpoint callbacks.
            try:
                parameters = inspect.signature(self.agent_loop.run).parameters
                accepts_kwargs = any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
                if not accepts_kwargs:
                    agent_loop_kwargs = {
                        key: value
                        for key, value in agent_loop_kwargs.items()
                        if key in parameters
                    }
            except (TypeError, ValueError):
                pass
            try:
                execution = self.agent_loop.run(
                    [dict(message) for message in context.messages],
                    model,
                    llm_caller,
                    **agent_loop_kwargs,
                )
            finally:
                monitor_stop.set()
                cancel_monitor.join(timeout=1.0)
            observed_control = pending_control()
            if observed_control in {ControlAction.PAUSE.value, ControlAction.CANCEL.value}:
                return finish_control(execution, observed_control)
            persist_execution_messages(execution)
            provenance = self._safe_provenance(execution.provenance)
            usage_record = None
            if self.usage_ledger is not None:
                usage_node_id = str(node_id or (provenance.get("execution_node_ids") or [""])[0])
                usage_record = self.usage_ledger.record(
                    UsageDelta(
                        session_id=str(session_id),
                        turn_id=str(turn_id),
                        principal_id=str(principal_id),
                        tenant_id=str(tenant_id),
                        node_id=usage_node_id,
                        model_id=str(model),
                        prompt_tokens=execution.prompt_tokens,
                        completion_tokens=execution.completion_tokens,
                        tool_calls=len(execution.tool_calls_executed),
                        cpu_milliseconds=execution.resource_usage.get("cpu_milliseconds", 0),
                        gpu_milliseconds=execution.resource_usage.get("gpu_milliseconds", 0),
                        vram_byte_seconds=execution.resource_usage.get("vram_byte_seconds", 0),
                        network_bytes=execution.resource_usage.get("network_bytes", 0),
                        artifact_bytes=execution.resource_usage.get("artifact_bytes", 0),
                        external_cost_micros=execution.resource_usage.get("external_cost_micros", 0),
                        execution_job_ids=tuple(provenance.get("execution_job_ids", [])),
                        execution_node_ids=tuple(provenance.get("execution_node_ids", [])),
                    ),
                    idempotency_key=f"turn:{session_id}:{turn_id}",
                    budget=usage_budget,
                )
                self.session_store.record_event(
                    session_id,
                    "usage.recorded",
                    {
                        "usage_id": usage_record.usage_id,
                        "prompt_tokens": usage_record.delta.prompt_tokens,
                        "completion_tokens": usage_record.delta.completion_tokens,
                        "tool_calls": usage_record.delta.tool_calls,
                        "cpu_milliseconds": usage_record.delta.cpu_milliseconds,
                        "gpu_milliseconds": usage_record.delta.gpu_milliseconds,
                        "vram_byte_seconds": usage_record.delta.vram_byte_seconds,
                        "network_bytes": usage_record.delta.network_bytes,
                        "artifact_bytes": usage_record.delta.artifact_bytes,
                        "external_cost_micros": usage_record.delta.external_cost_micros,
                        "execution_job_ids": list(usage_record.delta.execution_job_ids),
                        "execution_node_ids": list(usage_record.delta.execution_node_ids),
                    },
                    turn_id=turn_id,
                )
            self.session_store.record_event(
                session_id,
                "turn.completed",
                {
                    "model": model,
                    "iterations": execution.iterations,
                    "tool_calls": len(execution.tool_calls_executed),
                    "total_tokens": execution.total_tokens,
                    "execution_job_ids": list(provenance.get("execution_job_ids", [])),
                    "execution_node_ids": list(provenance.get("execution_node_ids", [])),
                },
                turn_id=turn_id,
            )
            turn = self.session_store.transition_turn(turn_id, TurnStatus.COMPLETED)
            self.session_store.checkpoint_turn(turn_id, None)
        except AgentApprovalRequired as exc:
            persist_execution_messages(exc.execution)
            if self.trace_store is not None and root_span is not None:
                try:
                    provenance = self._safe_provenance(exc.execution.provenance)
                    self.trace_store.finish(
                        root_span.span_id,
                        status="waiting_for_approval",
                        attributes={
                            "execution_job_count": len(provenance.get("execution_job_ids", [])),
                            "execution_node_count": len(provenance.get("execution_node_ids", [])),
                        },
                    )
                except Exception:
                    pass
            self.session_store.record_event(
                session_id,
                "turn.waiting_for_approval",
                {"approval_ids": list(exc.approval_ids)},
                turn_id=turn_id,
            )
            turn = self.session_store.transition_turn(
                turn_id,
                TurnStatus.WAITING_FOR_APPROVAL,
                reason="approval_required",
            )
            return HarnessRun(
                self.session_store.get_session(session_id),
                turn,
                exc.execution,
                context,
                None,
            )
        except AgentControlRequested as exc:
            return finish_control(exc.execution, exc.action)
        except Exception as exc:
            if self.trace_store is not None and root_span is not None:
                try:
                    self.trace_store.finish(root_span.span_id, status="failed", attributes={"error_type": type(exc).__name__})
                except Exception:
                    pass
            self.session_store.record_event(
                session_id,
                "turn.failed",
                {"error_type": type(exc).__name__, "error": str(exc)},
                turn_id=turn_id,
            )
            turn = self.session_store.transition_turn(turn_id, TurnStatus.FAILED, error=str(exc))
            raise

        if self.trace_store is not None and root_span is not None:
            try:
                self.trace_store.finish(
                    root_span.span_id,
                    status="completed",
                    attributes={
                        "iterations": execution.iterations,
                        "tool_calls": len(execution.tool_calls_executed),
                        "execution_job_count": len(provenance.get("execution_job_ids", [])),
                        "execution_node_count": len(provenance.get("execution_node_ids", [])),
                        "execution_job_ids": provenance.get("execution_job_ids", []),
                        "execution_node_ids": provenance.get("execution_node_ids", []),
                    },
                )
            except Exception:
                pass

        return HarnessRun(self.session_store.get_session(session_id), turn, execution, context, usage_record)
