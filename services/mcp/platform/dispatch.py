"""Capability routing and lease-bound model dispatch for agent environments."""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from .leases import LeaseState, NodeLease, NodeLeaseStore, ReservationDenied
from .node_registry import NodeRecord, NodeRegistry
from .node_routing import CapabilityAwareNodeRouter, NodeRouteDecision, NodeRouteRequirement


class ModelDispatchError(RuntimeError):
    """Raised when a routed model request cannot be dispatched safely."""


class NoCapableNode(ModelDispatchError):
    """Raised when the verified inventory has no matching node."""


@dataclass(frozen=True)
class ModelDispatchResult:
    node_id: str
    model_id: str
    response: Mapping[str, Any]
    route: NodeRouteDecision
    lease: NodeLease


ModelExecutor = Callable[[NodeRecord, Mapping[str, Any]], Mapping[str, Any]]


class LeaseBoundModelDispatcher:
    """Route, reserve, execute and release one model request as one bounded unit."""

    def __init__(
        self,
        registry: NodeRegistry,
        leases: NodeLeaseStore,
        executor: ModelExecutor,
        *,
        router: CapabilityAwareNodeRouter | None = None,
        event_sink: Callable[[str, Mapping[str, Any]], None] | None = None,
        max_attempts: int = 1,
        retryable_error: Callable[[BaseException], bool] | None = None,
        node_stale_after_seconds: float | None = None,
    ) -> None:
        self.registry = registry
        self.leases = leases
        self.executor = executor
        self.router = router or CapabilityAwareNodeRouter()
        self.event_sink = event_sink
        if not 1 <= int(max_attempts) <= 8:
            raise ValueError("max_attempts must be between 1 and 8")
        self.max_attempts = int(max_attempts)
        self.retryable_error = retryable_error or (
            lambda error: isinstance(error, (ConnectionError, TimeoutError, OSError))
        )
        if node_stale_after_seconds is not None and float(node_stale_after_seconds) <= 0:
            raise ValueError("node_stale_after_seconds must be positive")
        self.node_stale_after_seconds = (
            float(node_stale_after_seconds) if node_stale_after_seconds is not None else None
        )

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.event_sink is not None:
            self.event_sink(event_type, dict(payload))

    @staticmethod
    def _validate_request(payload: Mapping[str, Any]) -> None:
        try:
            encoded = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ModelDispatchError("model request must be JSON-serializable") from exc
        if len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
            raise ModelDispatchError("model request exceeds the dispatch size limit")

    def dispatch(
        self,
        *,
        session_id: str,
        turn_id: str,
        model_id: str,
        requirement: NodeRouteRequirement,
        payload: Mapping[str, Any],
        idempotency_key: str,
        capacity_limit: int = 1,
        requested_slots: int = 1,
        ttl_seconds: int = 300,
        cancel_event: Any | None = None,
    ) -> ModelDispatchResult:
        def cancelled() -> bool:
            return cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)())

        def accepts_cancel(handler: Callable[..., Any]) -> bool:
            try:
                parameters = inspect.signature(handler).parameters.values()
            except (TypeError, ValueError):
                return False
            return "cancel_event" in inspect.signature(handler).parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )

        if cancelled():
            raise ModelDispatchError("model dispatch was cancelled")
        if requirement.model_id not in {None, str(model_id)}:
            raise ModelDispatchError("route requirement model does not match dispatch model")
        self._validate_request(payload)
        if self.node_stale_after_seconds is not None:
            self.registry.reconcile_stale_nodes(self.node_stale_after_seconds)
        excluded = set(requirement.excluded_node_ids)
        last_error: BaseException | None = None
        attempt = 0
        while attempt < self.max_attempts:
            if cancelled():
                raise ModelDispatchError("model dispatch was cancelled")
            attempt_requirement = replace(requirement, excluded_node_ids=frozenset(excluded))
            route = self.router.route(self.registry.routable_nodes(), attempt_requirement)
            candidates = tuple(
                candidate
                for candidate in route.candidates
                if candidate.accepted and candidate.node_id not in excluded
            )
            if not candidates:
                if last_error is not None:
                    raise ModelDispatchError("no fallback node satisfies the model capability requirement") from last_error
                raise NoCapableNode("no verified node satisfies the model capability requirement")

            # Reservation is part of scheduling, not an execution failure. A
            # busy first candidate must not prevent a verified second candidate
            # from serving the same request.
            selected = None
            node = None
            lease = None
            capacity_error: ReservationDenied | None = None
            attempt_key = idempotency_key if attempt == 0 else f"{idempotency_key}:retry:{attempt + 1}"
            for candidate in candidates:
                if cancelled():
                    raise ModelDispatchError("model dispatch was cancelled")
                candidate_node = self.registry.get(candidate.node_id)
                try:
                    candidate_lease = self.leases.reserve(
                        node_id=candidate_node.node_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        model_id=str(model_id),
                        requested_slots=requested_slots,
                        capacity_limit=capacity_limit,
                        ttl_seconds=ttl_seconds,
                        idempotency_key=attempt_key,
                    )
                except ReservationDenied as exc:
                    capacity_error = exc
                    excluded.add(candidate_node.node_id)
                    self._emit("mesh.dispatch.capacity_skipped", {
                        "node_id": candidate_node.node_id,
                        "model_id": str(model_id),
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "reason": "capacity_unavailable",
                    })
                    continue
                selected = candidate
                node = candidate_node
                lease = candidate_lease
                break
            if lease is None or selected is None or node is None:
                if capacity_error is not None:
                    raise ModelDispatchError("no capable node has available capacity") from capacity_error
                raise ModelDispatchError("no capable node could be reserved")
            if lease.status is not LeaseState.ACTIVE:
                raise ModelDispatchError("dispatch idempotency key refers to a closed node lease")
            attempt += 1
            selected_route = replace(route, selected=selected)
            self._emit("mesh.dispatch.started", {"node_id": node.node_id, "model_id": str(model_id), "lease_id": lease.lease_id, "session_id": session_id, "turn_id": turn_id, "attempt": attempt})
            try:
                contextual_executor = getattr(self.executor, "execute_dispatch", None)
                if callable(contextual_executor):
                    kwargs = {
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "model_id": str(model_id),
                        "lease": lease,
                    }
                    if cancel_event is not None and accepts_cancel(contextual_executor):
                        kwargs["cancel_event"] = cancel_event
                    response = contextual_executor(node, dict(payload), **kwargs)
                else:
                    if cancel_event is not None and accepts_cancel(self.executor):
                        response = self.executor(node, dict(payload), cancel_event=cancel_event)
                    else:
                        response = self.executor(node, dict(payload))
                if cancelled():
                    raise ModelDispatchError("model dispatch was cancelled")
                if not isinstance(response, Mapping):
                    raise ModelDispatchError("model executor returned a non-object response")
                returned_node = response.get("node_id")
                if returned_node is not None and str(returned_node) != node.node_id:
                    raise ModelDispatchError("model response node binding mismatch")
                returned_model = response.get("model") or response.get("model_id")
                if returned_model is not None and str(returned_model) != str(model_id):
                    raise ModelDispatchError("model response model binding mismatch")
                result = ModelDispatchResult(node.node_id, str(model_id), dict(response), selected_route, lease)
                self._emit("mesh.dispatch.completed", {"node_id": node.node_id, "model_id": str(model_id), "lease_id": lease.lease_id, "session_id": session_id, "turn_id": turn_id, "attempt": attempt})
                return result
            except Exception as exc:
                last_error = exc
                self._emit("mesh.dispatch.failed", {"node_id": node.node_id, "model_id": str(model_id), "lease_id": lease.lease_id, "error_type": type(exc).__name__, "session_id": session_id, "turn_id": turn_id, "attempt": attempt})
                excluded.add(node.node_id)
                if attempt >= self.max_attempts or not bool(self.retryable_error(exc)):
                    raise
                self._emit("mesh.dispatch.retrying", {"failed_node_id": node.node_id, "model_id": str(model_id), "session_id": session_id, "turn_id": turn_id, "attempt": attempt, "next_attempt": attempt + 1})
            finally:
                self.leases.release(lease.lease_id, reason="model_dispatch_finished")
        raise ModelDispatchError("model dispatch exhausted its retry budget") from last_error
