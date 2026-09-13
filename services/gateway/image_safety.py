"""ComputeMesh image-generation safety policy.

This module provides a fail-closed policy layer for image generation and image
editing. It is deliberately independent from a specific model/runtime so every
image backend must pass through the same safety contract.

The policy is designed for a public EU/DE-facing service. It is a technical
safety implementation, not legal advice. Production deployments should keep
jurisdiction-specific policy under legal review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Iterable, Sequence


class SafetyAction(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


class SafetyCategory(str, Enum):
    SEXUAL_MINORS = "sexual_minors"
    AGE_AMBIGUOUS_SEXUAL = "age_ambiguous_sexual"
    NONCONSENSUAL_INTIMATE = "nonconsensual_intimate"
    SEXUAL_DEEPFAKE = "sexual_deepfake"
    EXPLICIT_SEXUAL = "explicit_sexual"
    REAL_PERSON_SENSITIVE = "real_person_sensitive"
    IDENTITY_FRAUD = "identity_fraud"
    EXTREMISM_ILLEGAL = "extremism_illegal"
    HATE_TARGETING = "hate_targeting"
    GRAPHIC_VIOLENCE = "graphic_violence"
    SELF_HARM = "self_harm"
    DANGEROUS_WRONGDOING = "dangerous_wrongdoing"
    MEDICAL_GRAPHIC = "medical_graphic"
    COPYRIGHT_STYLE_IMPERSONATION = "copyright_style_impersonation"
    SAFE = "safe"


@dataclass(frozen=True)
class SafetyFinding:
    category: SafetyCategory
    action: SafetyAction
    reason_code: str
    explanation: str


@dataclass(frozen=True)
class SafetyDecision:
    action: SafetyAction
    findings: tuple[SafetyFinding, ...] = field(default_factory=tuple)

    @property
    def blocked(self) -> bool:
        return self.action is SafetyAction.BLOCK

    @property
    def needs_review(self) -> bool:
        return self.action is SafetyAction.REVIEW


# Conservative lexical layer. It is NOT the only production moderation layer;
# see ImageSafetyOrchestrator below. The goal is fast pre-screening before a
# stronger multilingual/multimodal classifier is called.
_MINOR_TERMS = {
    "child", "children", "kid", "kids", "minor", "underage", "teen", "teenager",
    "preteen", "schoolgirl", "schoolboy", "mädchen", "junge", "kind", "kinder",
    "minderjährig", "minderjaehrig", "jugendlich", "jugendliche", "schülerin", "schuelerin",
}
_SEXUAL_TERMS = {
    "nude", "naked", "porn", "pornographic", "sex", "sexual", "explicit", "genitals",
    "fetish", "erotic", "erotisch", "nackt", "pornografisch", "pornographisch", "sexuell",
    "intim", "genitalien",
}
_REAL_PERSON_TERMS = {
    "real person", "celebrity", "politician", "actor", "actress", "singer", "influencer",
    "öffentliche person", "oeffentliche person", "promi", "politiker", "politikerin",
    "schauspieler", "schauspielerin", "sänger", "saenger", "influencerin",
}
_DEEPFAKE_TERMS = {"deepfake", "face swap", "faceswap", "swap face", "gesicht tauschen", "gesichtstausch"}
_NONCONSENSUAL_TERMS = {
    "without consent", "non-consensual", "nonconsensual", "revenge porn", "leaked nude",
    "ohne einwilligung", "ohne zustimmung", "racheporno", "geleaktes nacktbild",
}
_IDENTITY_FRAUD_TERMS = {
    "fake id", "passport", "identity card", "driver license", "führerschein", "fuehrerschein",
    "personalausweis", "reisepass", "bank statement", "kontoauszug", "invoice forgery",
}
_HATE_TERMS = {
    "exterminate", "gas them", "kill all", "inferior race", "vernichten", "vergast", "alle töten",
    "alle toeten", "minderwertige rasse",
}
_EXTREMISM_TERMS = {
    "isis propaganda", "daesh propaganda", "terror recruitment", "terrorist recruitment",
    "terror propaganda", "terroristische propaganda", "terror rekrutierung",
}
_GRAPHIC_VIOLENCE_TERMS = {
    "gore", "dismemberment", "decapitation", "severed head", "graphic murder", "verstümmelung",
    "verstuemmelung", "enthauptung", "abgetrennter kopf",
}
_SELF_HARM_TERMS = {
    "self harm", "suicide", "cutting myself", "kill myself", "selbstverletzung", "suizid",
    "mich umbringen", "ritzen",
}
_DANGEROUS_TERMS = {
    "build a bomb", "improvised explosive", "poison someone", "make ricin", "brandbombe bauen",
    "bombe bauen", "jemanden vergiften", "ricin herstellen",
}
_MEDICAL_GRAPHIC_TERMS = {
    "open surgery", "graphic surgery", "bloody operation", "offene operation", "blutige operation",
}


def _normalize(text: str) -> str:
    value = (text or "").casefold()
    value = value.replace("ß", "ss")
    value = re.sub(r"[^\w\säöü-]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    t = _normalize(text)
    return any(_normalize(term) in t for term in terms)


def lexical_prompt_screen(prompt: str) -> SafetyDecision:
    """Fast conservative prompt screen.

    Production must combine this with a model-based multilingual classifier.
    Lexical misses therefore never count as a final safety clearance.
    """
    findings: list[SafetyFinding] = []
    has_minor = _contains_any(prompt, _MINOR_TERMS)
    has_sexual = _contains_any(prompt, _SEXUAL_TERMS)
    has_real_person = _contains_any(prompt, _REAL_PERSON_TERMS)
    has_deepfake = _contains_any(prompt, _DEEPFAKE_TERMS)

    if has_minor and has_sexual:
        findings.append(SafetyFinding(
            SafetyCategory.SEXUAL_MINORS,
            SafetyAction.BLOCK,
            "IMG_SAFETY_MINOR_SEXUAL",
            "Sexual content involving a minor or minor-coded subject is not permitted.",
        ))

    if has_sexual and _contains_any(prompt, _NONCONSENSUAL_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.NONCONSENSUAL_INTIMATE,
            SafetyAction.BLOCK,
            "IMG_SAFETY_NONCONSENSUAL_INTIMATE",
            "Non-consensual intimate imagery is not permitted.",
        ))

    if has_sexual and (has_deepfake or has_real_person):
        findings.append(SafetyFinding(
            SafetyCategory.SEXUAL_DEEPFAKE,
            SafetyAction.BLOCK,
            "IMG_SAFETY_SEXUAL_DEEPFAKE",
            "Sexualized real-person/deepfake generation is not permitted.",
        ))

    if has_sexual and not findings:
        findings.append(SafetyFinding(
            SafetyCategory.EXPLICIT_SEXUAL,
            SafetyAction.BLOCK,
            "IMG_SAFETY_EXPLICIT_SEXUAL",
            "Explicit sexual image generation is disabled on the public ComputeMesh service.",
        ))

    if has_real_person and not has_sexual:
        findings.append(SafetyFinding(
            SafetyCategory.REAL_PERSON_SENSITIVE,
            SafetyAction.REVIEW,
            "IMG_SAFETY_REAL_PERSON",
            "Real-person generation requires enhanced identity and context checks.",
        ))

    if _contains_any(prompt, _IDENTITY_FRAUD_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.IDENTITY_FRAUD,
            SafetyAction.BLOCK,
            "IMG_SAFETY_IDENTITY_DOCUMENT",
            "Fraudulent identity/document generation is not permitted.",
        ))

    if _contains_any(prompt, _EXTREMISM_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.EXTREMISM_ILLEGAL,
            SafetyAction.BLOCK,
            "IMG_SAFETY_EXTREMISM_PROPAGANDA",
            "Terrorist/extremist propaganda or recruitment material is not permitted.",
        ))

    if _contains_any(prompt, _HATE_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.HATE_TARGETING,
            SafetyAction.BLOCK,
            "IMG_SAFETY_HATE_TARGETING",
            "Dehumanizing or exterminatory targeted hate content is not permitted.",
        ))

    if _contains_any(prompt, _DANGEROUS_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.DANGEROUS_WRONGDOING,
            SafetyAction.BLOCK,
            "IMG_SAFETY_DANGEROUS_WRONGDOING",
            "Images materially facilitating dangerous wrongdoing are not permitted.",
        ))

    if _contains_any(prompt, _GRAPHIC_VIOLENCE_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.GRAPHIC_VIOLENCE,
            SafetyAction.REVIEW,
            "IMG_SAFETY_GRAPHIC_VIOLENCE",
            "Graphic violence requires contextual review.",
        ))

    if _contains_any(prompt, _SELF_HARM_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.SELF_HARM,
            SafetyAction.REVIEW,
            "IMG_SAFETY_SELF_HARM",
            "Self-harm related imagery requires contextual review.",
        ))

    if _contains_any(prompt, _MEDICAL_GRAPHIC_TERMS):
        findings.append(SafetyFinding(
            SafetyCategory.MEDICAL_GRAPHIC,
            SafetyAction.REVIEW,
            "IMG_SAFETY_MEDICAL_GRAPHIC",
            "Graphic medical imagery requires contextual review.",
        ))

    if not findings:
        return SafetyDecision(SafetyAction.ALLOW, ())

    if any(f.action is SafetyAction.BLOCK for f in findings):
        return SafetyDecision(SafetyAction.BLOCK, tuple(findings))
    return SafetyDecision(SafetyAction.REVIEW, tuple(findings))


@dataclass(frozen=True)
class ClassifierResult:
    """Normalized result from an external moderation classifier."""

    action: SafetyAction
    categories: tuple[str, ...] = ()
    confidence: float | None = None
    subject_age_min: int | None = None
    subject_age_max: int | None = None
    real_person_likelihood: float | None = None
    sexual_content_likelihood: float | None = None


class ImageSafetyError(RuntimeError):
    pass


class ImageSafetyOrchestrator:
    """Combines lexical, prompt-classifier and output-classifier decisions.

    Fail-closed invariants:
      * image generation cannot be enabled without both prompt and output
        moderation classifiers;
      * any classifier failure blocks generation;
      * sexual content + age uncertainty that includes under-18 blocks;
      * output moderation can only keep or increase restriction, never relax it.
    """

    def __init__(self, prompt_classifier, output_classifier) -> None:
        if prompt_classifier is None or output_classifier is None:
            raise ValueError("prompt_classifier and output_classifier are required")
        self.prompt_classifier = prompt_classifier
        self.output_classifier = output_classifier

    @staticmethod
    def _merge(decisions: Sequence[SafetyDecision]) -> SafetyDecision:
        findings = tuple(f for d in decisions for f in d.findings)
        if any(d.action is SafetyAction.BLOCK for d in decisions):
            return SafetyDecision(SafetyAction.BLOCK, findings)
        if any(d.action is SafetyAction.REVIEW for d in decisions):
            return SafetyDecision(SafetyAction.REVIEW, findings)
        return SafetyDecision(SafetyAction.ALLOW, findings)

    @staticmethod
    def _classifier_to_decision(result: ClassifierResult, *, phase: str) -> SafetyDecision:
        findings: list[SafetyFinding] = []

        # Fail closed where the classifier says sexual content and its age range
        # can include a minor. This includes uncertain/ambiguous ages.
        sexual = (result.sexual_content_likelihood or 0.0) >= 0.35 or any(
            c in {"sexual", "explicit_sexual", "nudity"} for c in result.categories
        )
        if sexual:
            age_min = result.subject_age_min
            age_max = result.subject_age_max
            if age_min is None or age_max is None or age_min < 18:
                findings.append(SafetyFinding(
                    SafetyCategory.AGE_AMBIGUOUS_SEXUAL,
                    SafetyAction.BLOCK,
                    f"IMG_SAFETY_{phase.upper()}_AGE_AMBIGUOUS_SEXUAL",
                    "Sexual content with minor or uncertain subject age is blocked.",
                ))

        if result.action is SafetyAction.BLOCK and not findings:
            findings.append(SafetyFinding(
                SafetyCategory.SAFE,
                SafetyAction.BLOCK,
                f"IMG_SAFETY_{phase.upper()}_CLASSIFIER_BLOCK",
                "The moderation classifier rejected this request/output.",
            ))
        elif result.action is SafetyAction.REVIEW and not findings:
            findings.append(SafetyFinding(
                SafetyCategory.SAFE,
                SafetyAction.REVIEW,
                f"IMG_SAFETY_{phase.upper()}_CLASSIFIER_REVIEW",
                "The moderation classifier requires contextual review.",
            ))

        if any(f.action is SafetyAction.BLOCK for f in findings):
            return SafetyDecision(SafetyAction.BLOCK, tuple(findings))
        if result.action is SafetyAction.REVIEW:
            return SafetyDecision(SafetyAction.REVIEW, tuple(findings))
        return SafetyDecision(result.action, tuple(findings))

    def moderate_prompt(self, prompt: str) -> SafetyDecision:
        lexical = lexical_prompt_screen(prompt)
        if lexical.blocked:
            return lexical
        try:
            classified = self.prompt_classifier(prompt)
        except Exception as exc:  # fail closed
            raise ImageSafetyError("prompt moderation unavailable") from exc
        return self._merge((lexical, self._classifier_to_decision(classified, phase="prompt")))

    def moderate_output(self, image_bytes: bytes, *, mime_type: str) -> SafetyDecision:
        if not image_bytes:
            raise ImageSafetyError("empty generated image")
        try:
            classified = self.output_classifier(image_bytes, mime_type=mime_type)
        except Exception as exc:  # fail closed
            raise ImageSafetyError("output moderation unavailable") from exc
        return self._classifier_to_decision(classified, phase="output")


BLOCKED_PUBLIC_IMAGE_CATEGORIES: tuple[str, ...] = (
    "sexual_minors",
    "age_ambiguous_sexual",
    "nonconsensual_intimate",
    "sexual_deepfake",
    "explicit_sexual",
    "identity_fraud",
    "extremism_illegal",
    "hate_targeting",
    "dangerous_wrongdoing",
)

REVIEW_IMAGE_CATEGORIES: tuple[str, ...] = (
    "real_person_sensitive",
    "graphic_violence",
    "self_harm",
    "medical_graphic",
)
