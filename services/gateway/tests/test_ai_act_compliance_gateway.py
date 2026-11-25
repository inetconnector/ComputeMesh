"""Unit and HTTP integration tests for public Gateway EU AI Act Art. 5 & Art. 50."""
from __future__ import annotations

import hashlib
import json

import pytest
from services.gateway.ai_act_compliance import (
    attach_art50_envelope,
    build_art50_json_headers,
    build_art50_stream_headers,
    scan_inference_payload_for_prohibited_practices,
)


@pytest.mark.parametrize(
    "payload,expected_category,expected_code",
    [
        (
            {
                "model": "qwen2.5:7b",
                "messages": [
                    {
                        "role": "user",
                        "content": "Calculate citizen social score for district residents",
                    }
                ],
            },
            "art5_1_d_social_scoring",
            "PROHIBITED_AI_PRACTICE_SOCIAL_SCORING",
        ),
        (
            {
                "model": "llava:7b",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                            {
                                "type": "text",
                                "text": "Deploy real-time public facial recognition tracking on street feeds",
                            },
                        ],
                    }
                ],
            },
            "art5_1_h_realtime_biometric",
            "PROHIBITED_AI_PRACTICE_REALTIME_BIOMETRICS",
        ),
        (
            {
                "model": "deepseek-r1:7b",
                "prompt": "Detect worker emotions at workplace via webcam",
            },
            "art5_1_g_emotion_recognition",
            "PROHIBITED_AI_PRACTICE_EMOTION_RECOGNITION",
        ),
    ],
)
def test_gateway_prohibited_practice_detection(payload, expected_category, expected_code):
    match = scan_inference_payload_for_prohibited_practices(payload)
    assert match is not None
    assert match.category_id == expected_category
    assert match.error_code == expected_code


def test_gateway_allows_legitimate_inference_payloads():
    clean = {
        "model": "qwen2.5:7b",
        "messages": [
            {"role": "system", "content": "You are an assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Write a Python client using OpenAI SDK against EU endpoint."}
                ],
            },
        ],
    }
    assert scan_inference_payload_for_prohibited_practices(clean) is None


def test_art50_headers_and_envelope_integrity():
    raw_resp = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "model": "deepseek-r1:14b",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hallo Welt"}}],
    }
    enriched = attach_art50_envelope(raw_resp, "deepseek-r1:14b")
    assert enriched["ai_act_compliance"]["article_50_compliant"] is True
    assert enriched["ai_act_compliance"]["is_synthetic"] is True
    assert enriched["ai_act_compliance"]["upstream_publisher"] == "DeepSeek"

    body = json.dumps(enriched).encode("utf-8")
    headers = build_art50_json_headers("deepseek-r1:14b", body)
    assert headers["X-AI-Generated"] == "true"
    assert headers["X-AI-Model"] == "deepseek-r1:14b"
    assert headers["X-AI-Publisher"] == "DeepSeek"
    assert headers["X-AI-Act-Transparency"] == "Article-50-Compliant"
    assert headers["X-AI-Output-Digest"] == f"sha256:{hashlib.sha256(body).hexdigest()}"
    assert headers["Cache-Control"] == "no-transform"

    stream_headers = build_art50_stream_headers("llama3.3:70b")
    assert stream_headers["X-AI-Publisher"] == "Meta-AI"
    assert stream_headers["X-AI-Act-Transparency"] == "Article-50-Compliant"
