"""Encrypted, ordered stream frames for protected OpenAI Chat Completions.

Each frame is an ordinary ConfidentialResponseEnvelope whose plaintext is a tiny
sequence wrapper around one OpenAI `chat.completion.chunk`.  The sequence number
and final marker are therefore authenticated and hidden from the gateway.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from protocol.confidential_envelope import (
    ConfidentialClientContext,
    ConfidentialEnvelope,
    ConfidentialEnvelopeError,
    ConfidentialResponseEnvelope,
    decrypt_confidential_response,
    encrypt_response_in_attested_recipient,
)
from services.common.secure_memory import secure_zero_memory


STREAM_SCHEMA_VERSION = 1
MAX_STREAM_SEQUENCE = 10_000_000


class ConfidentialStreamError(ValueError):
    pass


@dataclass(frozen=True)
class ConfidentialStreamEvent:
    sequence: int
    done: bool
    chunk: Mapping[str, Any] | None
    response_id: str


def encrypt_stream_event_in_attested_recipient(
    request_envelope: ConfidentialEnvelope | Mapping[str, Any],
    *,
    sequence: int,
    done: bool,
    chunk: Mapping[str, Any] | None,
    recipient_private_key: X25519PrivateKey,
) -> ConfidentialResponseEnvelope:
    _validate_sequence(sequence)
    if not isinstance(done, bool):
        raise ConfidentialStreamError("stream done flag must be boolean")
    if done:
        if chunk is not None:
            raise ConfidentialStreamError("final protected stream frame must not contain a chunk")
    else:
        _validate_openai_chunk(chunk)
    payload = {
        "schema_version": STREAM_SCHEMA_VERSION,
        "sequence": sequence,
        "done": done,
        "chunk": dict(chunk) if chunk is not None else None,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return encrypt_response_in_attested_recipient(
        request_envelope,
        raw,
        recipient_private_key=recipient_private_key,
    )


def decrypt_stream_event(
    response: ConfidentialResponseEnvelope | Mapping[str, Any],
    *,
    client_context: ConfidentialClientContext,
    expected_sequence: int,
) -> ConfidentialStreamEvent:
    _validate_sequence(expected_sequence)
    parsed = (
        response
        if isinstance(response, ConfidentialResponseEnvelope)
        else ConfidentialResponseEnvelope.from_dict(response)
    )
    try:
        plaintext = decrypt_confidential_response(parsed, client_context=client_context)
    except ConfidentialEnvelopeError as exc:
        raise ConfidentialStreamError("protected stream frame authentication failed") from exc
    try:
        try:
            value = json.loads(bytes(plaintext).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfidentialStreamError("protected stream frame is malformed") from exc
    finally:
        secure_zero_memory(plaintext)
    if not isinstance(value, dict) or set(value) != {"schema_version", "sequence", "done", "chunk"}:
        raise ConfidentialStreamError("protected stream frame contract is invalid")
    if value.get("schema_version") != STREAM_SCHEMA_VERSION:
        raise ConfidentialStreamError("unsupported protected stream frame version")
    sequence = value.get("sequence")
    done = value.get("done")
    chunk = value.get("chunk")
    _validate_sequence(sequence)
    if sequence != expected_sequence:
        raise ConfidentialStreamError("protected stream frame sequence mismatch")
    if not isinstance(done, bool):
        raise ConfidentialStreamError("protected stream frame done flag is invalid")
    if done:
        if chunk is not None:
            raise ConfidentialStreamError("final protected stream frame contains unexpected content")
    else:
        _validate_openai_chunk(chunk)
    return ConfidentialStreamEvent(
        sequence=sequence,
        done=done,
        chunk=chunk,
        response_id=parsed.response_id,
    )


def openai_sse_bytes(event: ConfidentialStreamEvent) -> bytes:
    """Translate locally decrypted protected event into standard OpenAI SSE."""
    if event.done:
        return b"data: [DONE]\n\n"
    assert event.chunk is not None
    raw = json.dumps(event.chunk, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"data: " + raw + b"\n\n"


def _validate_sequence(value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_STREAM_SEQUENCE:
        raise ConfidentialStreamError("invalid protected stream sequence")


def _validate_openai_chunk(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise ConfidentialStreamError("protected stream chunk must be an object")
    if not isinstance(value.get("id"), str) or not value.get("id"):
        raise ConfidentialStreamError("protected OpenAI chunk id is invalid")
    if value.get("object") != "chat.completion.chunk":
        raise ConfidentialStreamError("protected OpenAI chunk object is invalid")
    if not isinstance(value.get("created"), int):
        raise ConfidentialStreamError("protected OpenAI chunk created field is invalid")
    if not isinstance(value.get("model"), str) or not value.get("model"):
        raise ConfidentialStreamError("protected OpenAI chunk model is invalid")
    choices = value.get("choices")
    if not isinstance(choices, list):
        raise ConfidentialStreamError("protected OpenAI chunk choices are invalid")
    for choice in choices:
        if not isinstance(choice, Mapping) or not isinstance(choice.get("index"), int):
            raise ConfidentialStreamError("protected OpenAI stream choice is invalid")
        delta = choice.get("delta")
        if delta is not None and not isinstance(delta, Mapping):
            raise ConfidentialStreamError("protected OpenAI stream delta is invalid")
