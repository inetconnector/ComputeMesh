"""Bounded dynamic re-routing and fallback management for Agents Platform."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Iterable, Mapping

from .contracts import RequestEnvelope, RoutingDecision
from .skill_registry import PersistentSkillRegistry
from .skill_router import SkillRouter
from .validation import ErrorCode, PlatformError, RecoveryAction


@dataclass(frozen=True)
class RerouteAttempt:
    index: int
    trigger: str
    previous_skills: tuple[str, ...]
    selected_skills: tuple[str, ...]
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RerouteResult:
    decision: RoutingDecision
    attempts: tuple[RerouteAttempt, ...]
    exhausted: bool


class RerouteManager:
    """Bounded re-routing with visited-route protection and declared fallbacks."""

    def __init__(
        self,
        router: SkillRouter,
        registry: PersistentSkillRegistry,
        *,
        max_reroutes: int = 3,
        deadline_seconds: float = 30.0,
    ) -> None:
        self.router = router
        self.registry = registry
        self.max_reroutes = max(0, min(20, int(max_reroutes)))
        self.deadline_seconds = max(0.1, float(deadline_seconds))

    def reroute(
        self,
        envelope: RequestEnvelope,
        previous: RoutingDecision,
        *,
        trigger: str,
        error: PlatformError | None = None,
        available_tools: Iterable[str] | None = None,
    ) -> RerouteResult:
        started = time.monotonic()
        attempts: list[RerouteAttempt] = []
        visited: set[tuple[str, ...]] = {tuple(previous.selected_skills)}
        current = previous

        for index in range(1, self.max_reroutes + 1):
            if time.monotonic() - started > self.deadline_seconds:
                break
            fallback = self._fallback_decision(envelope, current, visited)
            if fallback is not None:
                decision = fallback
            else:
                amended = self._amend_envelope(envelope, trigger, error, visited)
                decision = self.router.route(amended, available_tools=available_tools)
            key = tuple(decision.selected_skills)
            attempts.append(
                RerouteAttempt(
                    index=index,
                    trigger=trigger,
                    previous_skills=tuple(current.selected_skills),
                    selected_skills=key,
                    status=decision.status,
                    reasons=tuple(decision.reasons),
                )
            )
            if decision.status == "ROUTED" and key and key not in visited:
                return RerouteResult(decision, tuple(attempts), False)
            visited.add(key)
            current = decision
        return RerouteResult(current, tuple(attempts), True)

    def _fallback_decision(
        self,
        envelope: RequestEnvelope,
        previous: RoutingDecision,
        visited: set[tuple[str, ...]],
    ) -> RoutingDecision | None:
        fallbacks: list[str] = []
        for skill_id in previous.selected_skills:
            manifest = self.registry.get(skill_id, include_inactive=False)
            if manifest:
                fallbacks.extend(manifest.fallback_skills)
        for fallback_id in dict.fromkeys(fallbacks):
            manifest = self.registry.get(fallback_id, include_inactive=False)
            if manifest is None:
                continue
            candidate_key = (fallback_id,)
            if candidate_key in visited:
                continue
            explicit = RequestEnvelope.from_text(
                envelope.raw_text,
                explicit_skill=fallback_id,
                attachments=envelope.attachments,
                requested_output=envelope.requested_output,
                context_budget=envelope.context_budget,
                privacy_level=envelope.privacy_level,
                side_effect_intent=envelope.side_effect_intent,
            )
            return self.router.route(explicit)
        return None

    @staticmethod
    def _amend_envelope(
        envelope: RequestEnvelope,
        trigger: str,
        error: PlatformError | None,
        visited: set[tuple[str, ...]],
    ) -> RequestEnvelope:
        failure_signal = f" execution feedback: {trigger}"
        if error:
            failure_signal += f" error={error.code.value} recovery={error.recovery.value}"
        visited_flat = ",".join(skill for route in sorted(visited) for skill in route)
        if visited_flat:
            failure_signal += f" unavailable_or_visited_skills={visited_flat}"
        return RequestEnvelope.from_text(
            envelope.raw_text + failure_signal,
            attachments=envelope.attachments,
            requested_output=envelope.requested_output,
            context_budget=envelope.context_budget,
            privacy_level=envelope.privacy_level,
            side_effect_intent=envelope.side_effect_intent,
        )


def reroute_trigger_for_error(error: PlatformError) -> str | None:
    if error.recovery in {RecoveryAction.REROUTE, RecoveryAction.FALLBACK_SKILL, RecoveryAction.FALLBACK_TOOL}:
        return error.code.value
    if error.code in {
        ErrorCode.TOOL_UNAVAILABLE,
        ErrorCode.DATA_CONFLICT,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.OUTPUT_CONTRACT_FAILED,
    }:
        return error.code.value
    return None
