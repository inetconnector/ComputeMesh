"""Request intent/entity/constraint and risk analysis for Agents Platform.

This module produces observable structured signals used by routing and policy.
It is deliberately deterministic and does not expose hidden model reasoning.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any, Iterable

from .contracts import RequestEnvelope, RiskLevel, SideEffectLevel


class RequirementStrength(str, Enum):
    MUST = "MUST"
    SHOULD = "SHOULD"
    MAY = "MAY"


@dataclass(frozen=True)
class IntentSignal:
    name: str
    confidence: float
    evidence: str
    required_capabilities: tuple[str, ...] = ()
    candidate_outputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntitySignal:
    entity_type: str
    value: str
    evidence: str


@dataclass(frozen=True)
class ConstraintSignal:
    name: str
    value: str
    strength: RequirementStrength
    evidence: str


@dataclass(frozen=True)
class RequestAnalysis:
    request_id: str
    intents: tuple[IntentSignal, ...]
    entities: tuple[EntitySignal, ...]
    constraints: tuple[ConstraintSignal, ...]
    risk_level: RiskLevel
    side_effect: SideEffectLevel
    required_capabilities: tuple[str, ...]
    requested_outputs: tuple[str, ...]
    ambiguity_signals: tuple[str, ...] = ()
    freshness_required: bool = False
    external_data_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["risk_level"] = self.risk_level.value
        value["side_effect"] = self.side_effect.value
        return value


_INTENT_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    ("research", ("research", "recherche", "suche", "find", "look up", "aktuell", "latest"), ("SEARCH", "FETCH"), ("research_summary",)),
    ("analyze", ("analyse", "analysiere", "analyze", "bewerte", "compare", "vergleiche"), ("ANALYSIS",), ("analysis",)),
    ("create", ("erstelle", "create", "generate", "baue", "build", "write", "schreibe"), ("CREATE",), ("artifact",)),
    ("modify", ("ändere", "bearbeite", "modify", "edit", "update", "patch", "refactor"), ("WRITE",), ("modified_resource",)),
    ("execute", ("führe aus", "execute", "run", "starte", "deploy", "installiere"), ("EXECUTE",), ("execution_result",)),
    ("delete", ("lösche", "delete", "remove", "entferne", "drop"), ("WRITE",), ("deletion_result",)),
    ("send", ("sende", "send", "verschicke", "publish", "veröffentliche"), ("WRITE", "EXTERNAL_ACTION"), ("action_result",)),
    ("plan", ("plane", "plan", "roadmap", "strategie", "strategy"), ("PLANNING",), ("plan",)),
)

_OUTPUT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pdf", re.compile(r"\bpdf\b", re.I)),
    ("spreadsheet", re.compile(r"\b(xlsx|excel|spreadsheet|tabelle)\b", re.I)),
    ("document", re.compile(r"\b(docx|word|document|dokument)\b", re.I)),
    ("presentation", re.compile(r"\b(pptx|powerpoint|slides?|präsentation)\b", re.I)),
    ("image", re.compile(r"\b(image|bild|grafik|photo|foto)\b", re.I)),
    ("code", re.compile(r"\b(code|python|javascript|typescript|patch|commit)\b", re.I)),
)

_FILE_RE = re.compile(r"(?<![\w/])([\w .-]+\.(?:pdf|docx|xlsx|csv|pptx|json|ya?ml|md|py|js|ts|html|css))\b", re.I)
_URL_RE = re.compile(r"https?://[^\s<>\]\[()]+", re.I)
_MONEY_RE = re.compile(r"(?:€|\$|£)\s?\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s?(?:EUR|USD|GBP)\b", re.I)
_DATE_RE = re.compile(r"\b(?:20\d{2}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]20\d{2})\b")


class RequestAnalyzer:
    """Deterministic first-pass analyzer feeding router/policy decisions."""

    def analyze(self, envelope: RequestEnvelope) -> RequestAnalysis:
        text = envelope.raw_text
        normalized = envelope.normalized_text
        intents: list[IntentSignal] = []
        capability_set: set[str] = set()
        output_set: set[str] = set()

        for name, terms, capabilities, outputs in _INTENT_RULES:
            matches = [term for term in terms if term.casefold() in normalized]
            if not matches:
                continue
            confidence = min(0.98, 0.62 + 0.1 * min(3, len(matches)))
            intents.append(IntentSignal(name, confidence, matches[0], capabilities, outputs))
            capability_set.update(capabilities)
            output_set.update(outputs)

        if not intents:
            intents.append(IntentSignal("informational", 0.45, "default_non_action_request", ("REASONING",), ("answer",)))
            capability_set.add("REASONING")
            output_set.add("answer")

        entities: list[EntitySignal] = []
        for match in _URL_RE.finditer(text):
            entities.append(EntitySignal("url", match.group(0), match.group(0)))
            capability_set.add("WEB_FETCH")
        for match in _FILE_RE.finditer(text):
            value = match.group(1).strip()
            entities.append(EntitySignal("file", value, value))
            capability_set.add("FILE_ACCESS")
        for match in _MONEY_RE.finditer(text):
            entities.append(EntitySignal("money", match.group(0), match.group(0)))
        for match in _DATE_RE.finditer(text):
            entities.append(EntitySignal("date", match.group(0), match.group(0)))

        constraints: list[ConstraintSignal] = []
        explicit = tuple(envelope.explicit_constraints)
        for constraint in explicit:
            constraints.append(ConstraintSignal("explicit", constraint, RequirementStrength.MUST, constraint))
        negative_matches = re.findall(r"\b(?:nicht|never|do not|don't|ohne|kein(?:e|en)?)\b[^,.!?;]{0,100}", text, flags=re.I)
        for value in negative_matches:
            constraints.append(ConstraintSignal("negative", value.strip(), RequirementStrength.MUST, value.strip()))
        if envelope.time_budget_ms is not None:
            constraints.append(ConstraintSignal("time_budget_ms", str(envelope.time_budget_ms), RequirementStrength.MUST, "request_envelope"))
        if envelope.cost_budget:
            constraints.append(ConstraintSignal("cost_budget", str(envelope.cost_budget), RequirementStrength.MUST, "request_envelope"))
        if envelope.context_budget is not None:
            constraints.append(ConstraintSignal("context_budget", str(envelope.context_budget), RequirementStrength.MUST, "request_envelope"))
        if envelope.privacy_level and envelope.privacy_level != "default":
            constraints.append(ConstraintSignal("privacy_level", envelope.privacy_level, RequirementStrength.MUST, "request_envelope"))

        for output_name, pattern in _OUTPUT_PATTERNS:
            if pattern.search(text):
                output_set.add(output_name)

        side_effect, risk = self._classify_risk(normalized, envelope.side_effect_intent)
        freshness = bool(re.search(r"\b(today|heute|latest|aktuell|current|jetzt|neueste|recent)\b", normalized, re.I))
        external = bool({"SEARCH", "FETCH", "WEB_FETCH", "EXTERNAL_ACTION"} & capability_set or entities)
        ambiguity: list[str] = []
        action_intents = {intent.name for intent in intents if intent.name in {"modify", "execute", "delete", "send"}}
        if action_intents and not entities and len(text.strip()) < 40:
            ambiguity.append("action_target_not_explicit")
        if len({intent.name for intent in intents}) >= 4:
            ambiguity.append("many_intents_detected")

        intents.sort(key=lambda item: (-item.confidence, item.name))
        return RequestAnalysis(
            request_id=envelope.request_id,
            intents=tuple(intents),
            entities=tuple(entities),
            constraints=tuple(constraints),
            risk_level=risk,
            side_effect=side_effect,
            required_capabilities=tuple(sorted(capability_set)),
            requested_outputs=tuple(sorted(output_set)),
            ambiguity_signals=tuple(ambiguity),
            freshness_required=freshness,
            external_data_required=external,
        )

    @staticmethod
    def _classify_risk(normalized: str, declared: SideEffectLevel) -> tuple[SideEffectLevel, RiskLevel]:
        side_effect = declared
        if re.search(r"\b(delete|lösche|remove|entferne|publish|veröffentliche|send|sende|buy|kaufe|pay|bezahle|kündige|cancel account)\b", normalized, re.I):
            side_effect = max((side_effect, SideEffectLevel.WRITE_IRREVERSIBLE), key=lambda item: item.rank)
        elif re.search(r"\b(edit|modify|update|patch|create file|erstelle datei|ändere|schreibe in)\b", normalized, re.I):
            side_effect = max((side_effect, SideEffectLevel.WRITE_REVERSIBLE), key=lambda item: item.rank)
        if re.search(r"\b(run|execute|shell|terminal|deploy|install|führe aus|starte)\b", normalized, re.I):
            side_effect = max((side_effect, SideEffectLevel.EXECUTE), key=lambda item: item.rank)
        if side_effect in {SideEffectLevel.EXECUTE, SideEffectLevel.WRITE_IRREVERSIBLE}:
            risk = RiskLevel.HIGH
        elif side_effect == SideEffectLevel.WRITE_REVERSIBLE:
            risk = RiskLevel.MEDIUM
        elif side_effect == SideEffectLevel.READ:
            risk = RiskLevel.LOW
        else:
            risk = RiskLevel.LOW
        if re.search(r"\b(secret|password|passwort|token|private key|credential|medizin|medical|bank|payment|zahlung)\b", normalized, re.I):
            risk = RiskLevel.CRITICAL if side_effect.rank >= SideEffectLevel.WRITE_IRREVERSIBLE.rank else RiskLevel.HIGH
        return side_effect, risk


def aggregate_capabilities(analyses: Iterable[RequestAnalysis]) -> tuple[str, ...]:
    return tuple(sorted({capability for analysis in analyses for capability in analysis.required_capabilities}))
