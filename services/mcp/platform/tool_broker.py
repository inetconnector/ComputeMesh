"""Session-aware broker for safe Agent Platform tool calls.

The broker is a thin adapter over ``SafeToolExecutor``. It adds durable
lifecycle events without copying tool results, credentials or private policy
data into the session event stream.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import (
    SideEffectLevel,
    ToolAuthorizationGrant,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolMode,
)
from .session import AgentSessionStore, SessionStateConflict
from .tool_execution import PolicyToolRegistryProxy, SafeToolExecutor


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BrokerCall:
    """The public, non-sensitive identity of one brokered tool call."""

    session_id: str | None
    turn_id: str | None
    tool_id: str
    call_id: str
    arguments_digest: str


class AgentToolBroker:
    """Execute tools through the existing policy and idempotency boundary."""

    def __init__(
        self,
        executor: SafeToolExecutor,
        *,
        session_store: AgentSessionStore | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        is_owner: bool = True,
        owner_id: str | None = None,
        request_id: str | None = None,
        allowed_tools: tuple[str, ...] | None = None,
        max_side_effect: SideEffectLevel = SideEffectLevel.EXECUTE,
        authorization_grants: Mapping[str, ToolAuthorizationGrant] | None = None,
        approved_approval_ids: tuple[str, ...] | list[str] = (),
    ) -> None:
        self.executor = executor
        self.session_store = session_store
        self.session_id = session_id
        self.turn_id = turn_id
        self.is_owner = bool(is_owner)
        self.owner_id = owner_id
        self.request_id = request_id
        self.allowed_tools = None if allowed_tools is None else set(allowed_tools)
        self.max_side_effect = max_side_effect
        self.authorization_grants = dict(authorization_grants or {})
        self.approved_approval_ids = {str(value) for value in approved_approval_ids if str(value).strip()}

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.session_store is None or not self.session_id:
            return
        self.session_store.record_event(self.session_id, event_type, payload, turn_id=self.turn_id)

    def _call(self, name: str, arguments: Mapping[str, Any], call_id: str) -> BrokerCall:
        manifest = self.executor.capabilities.get(name)
        return BrokerCall(
            session_id=self.session_id,
            turn_id=self.turn_id,
            tool_id=manifest.tool_id if manifest is not None else str(name),
            call_id=str(call_id),
            arguments_digest=_digest(dict(arguments)),
        )

    def _manifest_allowed(self, name: str) -> bool:
        manifest = self.executor.capabilities.get(name)
        if manifest is None:
            return False
        if self.allowed_tools is not None and manifest.name not in self.allowed_tools and manifest.tool_id not in self.allowed_tools:
            return False
        return manifest.side_effect.rank <= self.max_side_effect.rank

    def _grant_for(self, name: str, arguments: dict[str, Any]) -> ToolAuthorizationGrant | None:
        manifest = self.executor.capabilities.get(name)
        if manifest is None:
            return None
        grant = self.authorization_grants.get(manifest.tool_id) or self.authorization_grants.get(manifest.name)
        if grant is None:
            return None
        grant.validate(tool_id=manifest.tool_id, request_id=self.request_id, arguments=arguments)
        return grant

    @staticmethod
    def present(result: ToolExecutionResult) -> Any:
        """Convert the internal result to the legacy AgentLoop tool shape."""
        return PolicyToolRegistryProxy._present(result)

    def execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        call_id: str = "",
        is_owner: bool | None = None,
        owner_id: str | None = None,
    ) -> Any:
        call = self._call(name, arguments, call_id or "call_unknown")
        self._emit("tool.requested", {
            "tool_id": call.tool_id,
            "call_id": call.call_id,
            "arguments_digest": call.arguments_digest,
        })
        manifest = self.executor.capabilities.get(name)
        result: ToolExecutionResult
        approval_id = ""
        approval_pending = False
        execution_allowed = True
        if manifest is None:
            result = ToolExecutionResult(status="blocked", tool_id=call.tool_id, mode=ToolMode.EXECUTE, error="tool manifest not found")
        elif not self._manifest_allowed(name):
            result = ToolExecutionResult(status="blocked", tool_id=manifest.tool_id, mode=ToolMode.EXECUTE, error="tool is not allowed by broker policy")
        else:
            safe_auto = manifest.side_effect.rank <= SideEffectLevel.READ.rank and not manifest.confirmation_required
            try:
                grant = None if safe_auto else self._grant_for(name, arguments)
                if not safe_auto and grant is None and self.session_store is not None and self.session_id:
                    approved_id = ""
                    for candidate_id in self.approved_approval_ids:
                        try:
                            candidate = self.session_store.get_approval(candidate_id)
                        except KeyError:
                            continue
                        if (
                            candidate.status.value == "approved"
                            and candidate.session_id == str(self.session_id)
                            and candidate.turn_id == (str(self.turn_id) if self.turn_id is not None else None)
                            and candidate.tool_id == manifest.tool_id
                            and candidate.arguments_digest == call.arguments_digest
                        ):
                            approved_id = candidate.approval_id
                            break
                    if self.approved_approval_ids and not approved_id:
                        execution_allowed = False
                        result = ToolExecutionResult(
                            status="blocked",
                            tool_id=manifest.tool_id,
                            mode=ToolMode.EXECUTE,
                            error="approved action does not match this exact tool request",
                        )
                    elif approved_id:
                        self.session_store.consume_approval(
                            approved_id,
                            session_id=str(self.session_id),
                            turn_id=self.turn_id,
                            tool_id=manifest.tool_id,
                            arguments_digest=call.arguments_digest,
                        )
                        approval_id = approved_id
                        grant = None
                    else:
                        principal_id = self.owner_id or self.session_store.get_session(self.session_id).principal_id
                    if not self.approved_approval_ids and not approved_id and principal_id:
                        approval = self.session_store.create_approval(
                            self.session_id,
                            turn_id=self.turn_id,
                            tool_id=manifest.tool_id,
                            call_id=call.call_id,
                            arguments_digest=call.arguments_digest,
                            principal_id=principal_id,
                        )
                        approval_id = approval.approval_id
                        approval_pending = True
                        result = ToolExecutionResult(
                            status="confirmation_required",
                            tool_id=manifest.tool_id,
                            mode=ToolMode.EXECUTE,
                            confirmation_required=True,
                            provenance={
                                "source": manifest.source,
                                "executed": False,
                                "approval_id": approval_id,
                            },
                        )
                    elif not approved_id and not self.approved_approval_ids:
                        grant = None
                if approval_pending or not execution_allowed:
                    grant = None
                else:
                    context = ToolExecutionContext(
                        mode=ToolMode.EXECUTE,
                        is_owner=self.is_owner if is_owner is None else bool(is_owner),
                        # A durable, exact approval is an authorization grant
                        # for this one consumed call. Without this branch the
                        # broker would consume the approval but the executor
                        # would still reject the side effect as unauthorized.
                        authorized=safe_auto or bool(grant and grant.authorized) or bool(approval_id),
                        confirmed=safe_auto or bool(grant and grant.confirmed) or bool(approval_id),
                        owner_id=owner_id or self.owner_id,
                        # The approval ID is the stable one-shot idempotency
                        # key when no separate authorization grant supplied
                        # one. This prevents an approved non-idempotent write
                        # from being rejected after the approval was consumed.
                        idempotency_key=(approval_id or (None if grant is None else grant.idempotency_key)),
                        request_id=self.request_id,
                        allowed_permissions=() if grant is None else grant.allowed_permissions,
                    )
            except (PermissionError, SessionStateConflict) as exc:
                result = ToolExecutionResult(status="blocked", tool_id=manifest.tool_id, mode=ToolMode.EXECUTE, error=str(exc))
            else:
                if not approval_pending and execution_allowed:
                    self._emit("tool.started", {
                        "tool_id": call.tool_id,
                        "call_id": call.call_id,
                        "arguments_digest": call.arguments_digest,
                    })
                    result = self.executor.execute(name, arguments, context)
                    if approval_id:
                        result = ToolExecutionResult(
                            status=result.status,
                            tool_id=result.tool_id,
                            mode=result.mode,
                            result=result.result,
                            error=result.error,
                            confirmation_required=result.confirmation_required,
                            idempotency_replay=result.idempotency_replay,
                            provenance={**dict(result.provenance), "approval_id": approval_id},
                        )

        event_payload: dict[str, Any] = {
            "tool_id": call.tool_id,
            "call_id": call.call_id,
            "status": result.status,
            "result_digest": _digest(result.result) if result.result is not None else "",
            "idempotency_replay": result.idempotency_replay,
            "confirmation_required": result.confirmation_required,
        }
        if approval_id:
            event_payload["approval_id"] = approval_id
        if result.error:
            event_payload["error_present"] = True
        if not approval_pending:
            self._emit(
                "approval.required" if result.status == "confirmation_required" else ("tool.completed" if result.status == "completed" else "tool.failed"),
                event_payload,
            )
        return self.present(result)

    def execute_tools_batch(
        self,
        tool_calls: list[dict[str, Any]],
        *,
        is_owner: bool | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute in input order so side effects cannot race accidentally."""
        results: list[dict[str, Any]] = []
        for index, tool_call in enumerate(tool_calls):
            call_id = str(tool_call.get("id") or f"call_{index + 1}")
            function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
            name = str(function.get("name") or "")
            raw_arguments = function.get("arguments", {})
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except Exception as exc:
                    results.append({"id": call_id, "name": name, "arguments": {}, "result": {"error": f"invalid JSON arguments: {exc}"}})
                    continue
            else:
                arguments = raw_arguments
            if not isinstance(arguments, dict):
                results.append({"id": call_id, "name": name, "arguments": {}, "result": {"error": "arguments must be an object"}})
                continue
            presented = self.execute_tool(name, arguments, call_id=call_id, is_owner=is_owner, owner_id=owner_id)
            results.append({
                "id": call_id,
                "name": name,
                "arguments": arguments,
                "result": presented,
            })
            if isinstance(presented, dict) and presented.get("status") == "confirmation_required":
                break
        return results
