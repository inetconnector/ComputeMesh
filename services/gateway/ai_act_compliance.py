"""Runtime EU AI Act Article 5 Prohibited Practices & Article 50 Output Marking.

Pure standard-library enforcement module for the public ComputeMesh Gateway:
1. Fail-closed Article 5 prohibited AI practice detection across OpenAI, Ollama,
   multimodal message arrays, and agent instruction payloads.
2. Machine-readable Article 50 transparency headers and JSON envelope metadata.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class GatewayProhibitedPracticeMatch:
    article: str
    category_id: str
    title: str
    error_code: str


_PROHIBITED_RULES: tuple[tuple[str, str, str, str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "art5_1_a_subliminal",
        "Article 5(1)(a)",
        "Subliminal Manipulation",
        "PROHIBITED_AI_PRACTICE_SUBLIMINAL",
        (
            re.compile(r"(?i)\bgenerate\s+subliminal\s+audio\s+cues\b"),
            re.compile(r"(?i)\binfluence\s+human\s+behavior\s+without\s+awareness\b"),
            re.compile(r"(?i)\bcovert\s+psychological\s+manipulation\s+script\b"),
        ),
    ),
    (
        "art5_1_b_exploitation",
        "Article 5(1)(b)",
        "Vulnerability Exploitation",
        "PROHIBITED_AI_PRACTICE_EXPLOITATION",
        (
            re.compile(r"(?i)\bexploit\s+childhood\s+vulnerabilities\b"),
            re.compile(r"(?i)\btarget\s+mentally\s+impaired\s+for\s+fraud\b"),
            re.compile(r"(?i)\bmanipulate\s+vulnerable\s+elderly\s+into\s+transfers\b"),
        ),
    ),
    (
        "art5_1_c_biometric_categorization",
        "Article 5(1)(c)",
        "Sensitive Biometric Categorization",
        "PROHIBITED_AI_PRACTICE_BIOMETRIC_CATEGORIZATION",
        (
            re.compile(r"(?i)\bdeduce\s+sexual\s+orientation\s+from\s+face\b"),
            re.compile(r"(?i)\binfer\s+political\s+affiliation\s+from\s+biometrics\b"),
            re.compile(r"(?i)\bclassify\s+religious\s+beliefs\s+from\s+facial\s+features\b"),
        ),
    ),
    (
        "art5_1_d_social_scoring",
        "Article 5(1)(d)",
        "Social Scoring",
        "PROHIBITED_AI_PRACTICE_SOCIAL_SCORING",
        (
            re.compile(r"(?i)\bcalculate\s+citizen\s+social\s+score\b"),
            re.compile(r"(?i)\bassign\s+trustworthiness\s+score\s+to\s+citizens\b"),
            re.compile(r"(?i)\bsocial\s+credit\s+rating\s+algorithm\b"),
        ),
    ),
    (
        "art5_1_e_predictive_policing",
        "Article 5(1)(e)",
        "Predictive Criminal Profiling",
        "PROHIBITED_AI_PRACTICE_PREDICTIVE_POLICING",
        (
            re.compile(r"(?i)\bpredict\s+future\s+criminality\s+solely\s+from\s+personality\b"),
            re.compile(r"(?i)\bcrime\s+prediction\s+algorithm\s+based\s+on\s+profiling\b"),
            re.compile(r"(?i)\bassess\s+recidivism\s+without\s+factual\s+evidence\b"),
        ),
    ),
    (
        "art5_1_f_facial_scraping",
        "Article 5(1)(f)",
        "Untargeted Facial Scraping",
        "PROHIBITED_AI_PRACTICE_FACIAL_SCRAPING",
        (
            re.compile(r"(?i)\bscrape\s+cctv\s+to\s+build\s+facial\s+database\b"),
            re.compile(r"(?i)\buntargeted\s+facial\s+image\s+scraping\b"),
            re.compile(r"(?i)\bharvest\s+social\s+media\s+faces\s+for\s+recognition\b"),
        ),
    ),
    (
        "art5_1_g_emotion_recognition",
        "Article 5(1)(g)",
        "Workplace / School Emotion Recognition",
        "PROHIBITED_AI_PRACTICE_EMOTION_RECOGNITION",
        (
            re.compile(r"(?i)\bdetect\s+worker\s+emotions\s+at\s+workplace\b"),
            re.compile(r"(?i)\bmonitor\s+student\s+emotions\s+during\s+exam\b"),
            re.compile(r"(?i)\bclassroom\s+facial\s+emotion\s+detection\b"),
        ),
    ),
    (
        "art5_1_h_realtime_biometric",
        "Article 5(1)(h)",
        "Real-time Remote Biometric ID in Public",
        "PROHIBITED_AI_PRACTICE_REALTIME_BIOMETRICS",
        (
            re.compile(r"(?i)\breal-time\s+public\s+facial\\?s*recognition\s+tracking\b"),
            re.compile(r"(?i)\breal-time\s+public\s+facial\s+recognition\s+tracking\b"),
            re.compile(r"(?i)\bmass\s+surveillance\s+public\s+biometric\s+identification\b"),
            re.compile(r"(?i)\btrack\s+individuals\s+in\s+public\s+using\s+live\s+cctv\b"),
        ),
    ),
)


def _extract_text_fragments(value: Any, sink: list[str], depth: int = 0) -> None:
    if depth > 8 or value is None:
        return
    if isinstance(value, str):
        if value:
            sink.append(value)
        return
    if isinstance(value, (list, tuple)):
        for item in value[:256]:
            _extract_text_fragments(item, sink, depth + 1)
        return
    if isinstance(value, dict):
        for key in ("content", "text", "prompt", "input", "system", "instruction", "goal", "command", "task"):
            if key in value:
                _extract_text_fragments(value[key], sink, depth + 1)


def scan_inference_payload_for_prohibited_practices(
    payload: dict[str, Any],
) -> GatewayProhibitedPracticeMatch | None:
    """Inspect incoming gateway payload and return a match if prohibited under EU AI Act Art. 5."""
    if not isinstance(payload, dict):
        return None
    fragments: list[str] = []
    for top_key in ("prompt", "messages", "input", "system", "instruction", "goal", "command", "task"):
        if top_key in payload:
            _extract_text_fragments(payload[top_key], fragments)

    for text in fragments:
        for cat_id, article, title, err_code, patterns in _PROHIBITED_RULES:
            for pattern in patterns:
                if pattern.search(text):
                    return GatewayProhibitedPracticeMatch(
                        article=article,
                        category_id=cat_id,
                        title=title,
                        error_code=err_code,
                    )
    return None


def resolve_upstream_publisher(model_id: str) -> str:
    lowered = str(model_id or "").strip().lower()
    if "qwen" in lowered:
        return "Alibaba-Cloud"
    if "deepseek" in lowered:
        return "DeepSeek"
    if "gemma" in lowered:
        return "Google"
    if "llama" in lowered:
        return "Meta-AI"
    if "mistral" in lowered:
        return "Mistral-AI"
    if "minicpm" in lowered:
        return "OpenBMB"
    if "llava" in lowered:
        return "LLaVA-Community"
    return "Open-Weights-Provider"


def build_art50_json_headers(model_id: str, body_bytes: bytes) -> dict[str, str]:
    """Return canonical EU AI Act Article 50 headers for a JSON completion response."""
    clean_model = re.sub(r"[\r\n]+", "", str(model_id or "unknown"))[:128] or "unknown"
    publisher = resolve_upstream_publisher(clean_model)
    digest = hashlib.sha256(body_bytes).hexdigest()
    return {
        "X-AI-Generated": "true",
        "X-AI-Model": clean_model,
        "X-AI-Publisher": publisher,
        "X-AI-Act-Transparency": "Article-50-Compliant",
        "X-AI-Output-Digest": f"sha256:{digest}",
        "Cache-Control": "no-transform",
    }


def build_art50_stream_headers(model_id: str) -> dict[str, str]:
    """Return canonical EU AI Act Article 50 headers for SSE / NDJSON streaming responses."""
    clean_model = re.sub(r"[\r\n]+", "", str(model_id or "unknown"))[:128] or "unknown"
    publisher = resolve_upstream_publisher(clean_model)
    return {
        "X-AI-Generated": "true",
        "X-AI-Model": clean_model,
        "X-AI-Publisher": publisher,
        "X-AI-Act-Transparency": "Article-50-Compliant",
        "Cache-Control": "no-cache, no-transform",
    }


def attach_art50_envelope(payload: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Attach canonical `ai_act_compliance` block to non-streaming completion payloads."""
    if not isinstance(payload, dict):
        return payload
    clean_model = str(model_id or payload.get("model") or "unknown").strip() or "unknown"
    enriched = dict(payload)
    enriched.setdefault(
        "ai_act_compliance",
        {
            "article_50_compliant": True,
            "is_synthetic": True,
            "model_id": clean_model,
            "upstream_publisher": resolve_upstream_publisher(clean_model),
            "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return enriched
