"""Hybrid, auditable skill router for ComputeMesh Agents Platform."""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from .contracts import RequestEnvelope, RouteCandidate, RoutingDecision, SkillManifest, SkillStatus
from .skill_registry import PersistentSkillRegistry

_TOKEN_RE = re.compile(r"[\wäöüßÀ-ÿ.-]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {tok.casefold().strip("._-") for tok in _TOKEN_RE.findall(text or "") if len(tok.strip("._-")) > 1}


def _phrase_present(phrase: str, normalized: str) -> bool:
    phrase_norm = " ".join(str(phrase).casefold().split())
    return bool(phrase_norm and phrase_norm in normalized)


def _semantic_overlap(request_tokens: set[str], skill: SkillManifest) -> float:
    corpus = " ".join((skill.skill_id, skill.name, skill.description, *skill.domains, *skill.intents, *skill.triggers, *skill.examples))
    skill_tokens = _tokens(corpus)
    if not request_tokens or not skill_tokens:
        return 0.0
    intersection = len(request_tokens & skill_tokens)
    union = len(request_tokens | skill_tokens)
    jaccard = intersection / union if union else 0.0
    coverage = intersection / len(request_tokens)
    return min(1.0, 0.45 * jaccard + 0.55 * coverage)


class SkillRouter:
    """Route requests with explicit, rule, lexical-semantic and capability signals.

    Reasons are compact observable signals; they do not expose hidden chain-of-thought.
    """

    def __init__(self, registry: PersistentSkillRegistry, *, minimum_score: float = 0.28, ambiguity_margin: float = 0.08, max_candidates: int = 12) -> None:
        self.registry = registry
        self.minimum_score = float(minimum_score)
        self.ambiguity_margin = float(ambiguity_margin)
        self.max_candidates = max(1, int(max_candidates))

    def _eligible(self, skill: SkillManifest, available_tools: set[str] | None) -> tuple[bool, str]:
        if skill.status not in {SkillStatus.ACTIVE, SkillStatus.EXPERIMENTAL}:
            return False, f"status={skill.status.value}"
        if available_tools is not None:
            missing = sorted(set(skill.required_tools) - available_tools)
            if missing:
                return False, f"missing_tools={','.join(missing)}"
        return True, ""

    def _score(self, envelope: RequestEnvelope, skill: SkillManifest) -> RouteCandidate:
        normalized = envelope.normalized_text
        signals: list[str] = []
        if any(_phrase_present(neg, normalized) for neg in (*skill.negative_triggers, *skill.anti_examples)):
            return RouteCandidate(skill.skill_id, -1.0, skill.priority, (), "negative_trigger")
        score = 0.0
        exact_hits = [trigger for trigger in skill.triggers if _phrase_present(trigger, normalized)]
        if exact_hits:
            score += min(0.62, 0.42 + 0.08 * min(2, len(exact_hits)))
            signals.append(f"trigger:{exact_hits[0]}")
        request_tokens = _tokens(normalized)
        intent_hits = [intent for intent in skill.intents if _tokens(intent) & request_tokens]
        if intent_hits:
            score += min(0.22, 0.11 * len(intent_hits))
            signals.append(f"intent:{intent_hits[0]}")
        domain_hits = [domain for domain in skill.domains if _tokens(domain) & request_tokens]
        if domain_hits:
            score += min(0.12, 0.06 * len(domain_hits))
            signals.append(f"domain:{domain_hits[0]}")
        semantic = _semantic_overlap(request_tokens, skill)
        if semantic > 0:
            score += min(0.32, semantic * 0.5)
            if semantic >= 0.12:
                signals.append(f"semantic:{semantic:.2f}")
        example_best = 0.0
        for example in skill.examples:
            e_tokens = _tokens(example)
            if e_tokens and request_tokens:
                example_best = max(example_best, len(e_tokens & request_tokens) / len(e_tokens | request_tokens))
        if example_best:
            score += min(0.15, example_best * 0.2)
            if example_best >= 0.2:
                signals.append(f"example:{example_best:.2f}")
        score += skill.priority / 1000.0
        return RouteCandidate(skill.skill_id, min(1.0, score), skill.priority, tuple(signals))

    def _dependency_closure(self, selected: Sequence[str]) -> tuple[list[str], list[tuple[str, str]], list[str]]:
        nodes: set[str] = set()
        edges: set[tuple[str, str]] = set()
        errors: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(skill_id: str) -> None:
            if skill_id in visited:
                return
            if skill_id in visiting:
                errors.append(f"dependency_cycle:{skill_id}")
                return
            skill = self.registry.get(skill_id, include_inactive=False)
            if skill is None:
                errors.append(f"missing_dependency:{skill_id}")
                return
            visiting.add(skill_id)
            nodes.add(skill_id)
            for dep in skill.dependencies:
                dep_skill = self.registry.get(dep, include_inactive=False)
                if dep_skill is None:
                    errors.append(f"missing_dependency:{skill_id}->{dep}")
                    continue
                edges.add((dep, skill_id))
                visit(dep)
            visiting.remove(skill_id)
            visited.add(skill_id)

        for sid in selected:
            visit(sid)
        return sorted(nodes), sorted(edges), errors

    def _resolve_conflicts(self, selected: list[str]) -> tuple[list[str], list[str]]:
        resolved: list[str] = []
        reasons: list[str] = []
        for sid in selected:
            skill = self.registry.get(sid, include_inactive=False)
            if skill is None:
                continue
            conflict = None
            for existing in resolved:
                other = self.registry.get(existing, include_inactive=False)
                if other and (existing in skill.conflicts_with or sid in other.conflicts_with):
                    conflict = other
                    break
            if conflict is None:
                resolved.append(sid)
                continue
            winner = skill if (skill.priority, skill.skill_id) > (conflict.priority, conflict.skill_id) else conflict
            loser = conflict if winner is skill else skill
            if winner.skill_id != conflict.skill_id:
                resolved.remove(conflict.skill_id)
                resolved.append(winner.skill_id)
            reasons.append(f"conflict:{winner.skill_id}>{loser.skill_id}")
        return resolved, reasons

    def _fit_context_budget(self, skill_ids: list[str], budget: int | None) -> tuple[list[str], int, list[str]]:
        manifests = [self.registry.get(sid, include_inactive=False) for sid in skill_ids]
        manifests = [m for m in manifests if m is not None]
        estimated = sum(max(0, m.estimated_context_tokens) for m in manifests)
        if budget is None or estimated <= budget:
            return skill_ids, estimated, []
        return [], estimated, [f"context_budget_exceeded:{estimated}>{budget}"]

    def route(self, envelope: RequestEnvelope, *, available_tools: Iterable[str] | None = None, allow_multi: bool = True) -> RoutingDecision:
        tools = None if available_tools is None else set(str(tool) for tool in available_tools)
        explicit = [sid for sid in envelope.user_selected_skills if sid]
        reasons: list[str] = []
        if explicit:
            selected: list[str] = []
            candidates: list[RouteCandidate] = []
            for sid in explicit:
                skill = self.registry.get(sid, include_inactive=False)
                if skill is None:
                    return RoutingDecision(envelope.request_id, "ABSTAIN", reasons=(f"explicit_skill_unavailable:{sid}",), abstained=True)
                eligible, why = self._eligible(skill, tools)
                if not eligible:
                    return RoutingDecision(envelope.request_id, "ABSTAIN", reasons=(f"explicit_skill_ineligible:{sid}:{why}",), abstained=True)
                selected.append(sid)
                candidates.append(RouteCandidate(sid, 1.0, skill.priority, ("explicit",)))
            reasons.append("explicit_skill_selection")
        else:
            scored: list[RouteCandidate] = []
            for skill in self.registry.active():
                eligible, _ = self._eligible(skill, tools)
                if not eligible:
                    continue
                candidate = self._score(envelope, skill)
                if not candidate.excluded_reason:
                    scored.append(candidate)
            scored.sort(key=lambda item: (-item.score, -item.priority, item.skill_id))
            candidates = scored[: self.max_candidates]
            if not candidates or candidates[0].score < self.minimum_score:
                return RoutingDecision(envelope.request_id, "ABSTAIN", candidates=tuple(candidates), reasons=("no_candidate_above_minimum_score",), abstained=True)
            if len(candidates) > 1 and candidates[1].score >= self.minimum_score:
                gap = candidates[0].score - candidates[1].score
                if gap < self.ambiguity_margin:
                    return RoutingDecision(envelope.request_id, "AMBIGUOUS", candidates=tuple(candidates), reasons=(f"ambiguity_gap:{gap:.3f}",), requires_user_choice=True)
            selected = [candidates[0].skill_id]
            if allow_multi:
                primary_tokens = _tokens(envelope.normalized_text)
                for candidate in candidates[1:]:
                    if candidate.score < max(self.minimum_score, candidates[0].score - 0.22):
                        break
                    skill = self.registry.get(candidate.skill_id, include_inactive=False)
                    if skill is None:
                        continue
                    signal_tokens = set().union(*(_tokens(x) for x in (*skill.intents, *skill.domains))) if (skill.intents or skill.domains) else set()
                    if signal_tokens & primary_tokens:
                        selected.append(candidate.skill_id)
                        if len(selected) >= 4:
                            break
        selected, conflict_reasons = self._resolve_conflicts(selected)
        reasons.extend(conflict_reasons)
        nodes, edges, dependency_errors = self._dependency_closure(selected)
        if dependency_errors:
            return RoutingDecision(envelope.request_id, "ABSTAIN", selected_skills=tuple(selected), candidates=tuple(candidates), dag_nodes=tuple(nodes), dag_edges=tuple(edges), reasons=tuple(reasons + dependency_errors), abstained=True)
        selected_plus_dependencies = list(dict.fromkeys([*selected, *nodes]))
        selected_plus_dependencies, estimated, budget_reasons = self._fit_context_budget(selected_plus_dependencies, envelope.context_budget)
        reasons.extend(budget_reasons)
        if not selected_plus_dependencies:
            return RoutingDecision(envelope.request_id, "ABSTAIN", candidates=tuple(candidates), reasons=tuple(reasons), abstained=True, context_tokens_estimated=estimated)
        kept = set(selected_plus_dependencies)
        filtered_nodes = tuple(node for node in nodes if node in kept)
        filtered_edges = tuple(edge for edge in edges if edge[0] in kept and edge[1] in kept)
        return RoutingDecision(
            envelope.request_id, "ROUTED", selected_skills=tuple(selected_plus_dependencies), candidates=tuple(candidates),
            dag_nodes=filtered_nodes, dag_edges=filtered_edges, reasons=tuple(reasons or ("hybrid_score_selected",)),
            context_tokens_estimated=estimated,
        )
