"""True streaming bridge from encrypted ComputeMesh frames to OpenAI SSE.

No OpenAI stream chunk leaves the local machine in plaintext.  The remote side
relays only encrypted response envelopes; sequence and final state are inside the
authenticated ciphertext and are checked locally before SSE emission.
"""
from __future__ import annotations

import json
from typing import Any, Iterator, Mapping
from urllib import error as urlerror
from urllib import request as urlrequest

from apps.client.confidential_openai import (
    ConfidentialOpenAIBridge,
    ConfidentialOpenAIError,
    HttpProtectedTransport,
    MAX_OPENAI_BODY_BYTES,
    prepare_openai_chat_request,
)
from protocol.confidential_envelope import ConfidentialBinding, create_confidential_request
from protocol.confidential_stream import (
    ConfidentialStreamError,
    decrypt_stream_event,
    openai_sse_bytes,
)


INTERNAL_STREAM_PATH = "/internal/v1/confidential/chat/completions/stream"
MAX_INTERNAL_STREAM_LINE_BYTES = 2 * 1024 * 1024


class HttpStreamingProtectedTransport(HttpProtectedTransport):
    def stream_execute(
        self,
        *,
        authorization: str,
        privacy_class: str,
        envelope: Mapping[str, Any],
    ) -> Iterator[Mapping[str, Any]]:
        raw = json.dumps(
            {"computemesh_privacy": privacy_class, "envelope": dict(envelope)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urlrequest.Request(
            self.base_url + INTERNAL_STREAM_PATH,
            data=raw,
            method="POST",
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
                "Accept": "application/x-ndjson",
                "Content-Length": str(len(raw)),
                "User-Agent": "ComputeMesh-Local-OpenAI-Proxy/1",
            },
        )
        try:
            response = urlrequest.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            )
        except urlerror.HTTPError as exc:
            raise ConfidentialOpenAIError(
                "Protected ComputeMesh stream was rejected",
                status=exc.code if 400 <= exc.code <= 599 else 502,
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise ConfidentialOpenAIError("Protected ComputeMesh stream is unavailable") from exc
        with response:
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/x-ndjson":
                raise ConfidentialOpenAIError("Protected stream returned invalid content type", status=502)
            while True:
                line = response.readline(MAX_INTERNAL_STREAM_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_INTERNAL_STREAM_LINE_BYTES:
                    raise ConfidentialOpenAIError("Protected stream frame is too large", status=502)
                if not line.strip():
                    continue
                try:
                    value = json.loads(line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ConfidentialOpenAIError("Protected stream returned malformed framing", status=502) from exc
                if not isinstance(value, dict):
                    raise ConfidentialOpenAIError("Protected stream returned invalid framing", status=502)
                yield value


class StreamingConfidentialOpenAIBridge(ConfidentialOpenAIBridge):
    transport: HttpStreamingProtectedTransport

    def stream(
        self,
        *,
        authorization: str,
        body: Mapping[str, Any],
    ) -> Iterator[bytes]:
        prepared = prepare_openai_chat_request(body)
        if not prepared.stream:
            raise ConfidentialOpenAIError(
                "Protected stream bridge requires stream=true",
                status=400,
                error_type="invalid_request_error",
                param="stream",
            )
        if not hasattr(self.transport, "stream_execute"):
            raise ConfidentialOpenAIError("Protected encrypted stream transport is not configured")
        descriptor = self.transport.create_session(
            authorization=authorization,
            model=prepared.model,
            privacy_class=self.privacy_class,
            max_prompt_tokens=prepared.max_prompt_tokens,
            max_completion_tokens=prepared.max_completion_tokens,
        )
        self.attestation_policy.verify_descriptor(descriptor)
        session = descriptor.get("session")
        account_id = descriptor.get("account_id")
        if not isinstance(session, Mapping) or not isinstance(account_id, str) or not account_id:
            raise ConfidentialOpenAIError("Protected streaming session descriptor is invalid")
        if session.get("model_id") != prepared.model:
            raise ConfidentialOpenAIError("Protected streaming session model binding mismatch")
        if session.get("privacy_class") != self.privacy_class:
            raise ConfidentialOpenAIError("Protected streaming privacy binding mismatch")
        if session.get("operation") != "chat_completion":
            raise ConfidentialOpenAIError("Protected streaming operation binding mismatch")
        if session.get("max_prompt_tokens") != prepared.max_prompt_tokens:
            raise ConfidentialOpenAIError("Protected streaming prompt reservation mismatch")
        if session.get("max_completion_tokens") != prepared.max_completion_tokens:
            raise ConfidentialOpenAIError("Protected streaming completion reservation mismatch")

        binding = ConfidentialBinding(
            account_id=account_id,
            job_id=str(session.get("job_id", "")),
            node_id=str(session.get("node_id", "")),
            attestation_nonce=str(session.get("attestation_nonce", "")),
            runtime_digest=str(session.get("runtime_digest", "")),
            data_plane_tls_sha256=str(session.get("data_plane_tls_sha256", "")),
            privacy_class=self.privacy_class,
            operation="chat_completion",
        )
        recipient_key = session.get("recipient_public_key")
        if not isinstance(recipient_key, str) or not recipient_key:
            raise ConfidentialOpenAIError("Protected streaming recipient key is invalid")
        envelope, client_context = create_confidential_request(
            prepared.encoded,
            recipient_public_key=recipient_key,
            binding=binding,
        )
        expected_sequence = 0
        done_seen = False
        try:
            for wire_event in self.transport.stream_execute(
                authorization=authorization,
                privacy_class=self.privacy_class,
                envelope=envelope.to_dict(),
            ):
                if set(wire_event) not in (
                    {"type", "response"},
                    {"type", "response", "billing_status"},
                ):
                    raise ConfidentialOpenAIError("Protected stream gateway framing is invalid", status=502)
                response_value = wire_event.get("response")
                if not isinstance(response_value, Mapping):
                    raise ConfidentialOpenAIError("Protected stream response envelope is missing", status=502)
                try:
                    event = decrypt_stream_event(
                        response_value,
                        client_context=client_context,
                        expected_sequence=expected_sequence,
                    )
                except ConfidentialStreamError as exc:
                    raise ConfidentialOpenAIError("Protected stream authentication failed", status=502) from exc
                if done_seen:
                    raise ConfidentialOpenAIError("Protected stream contained data after completion", status=502)
                expected_sequence += 1
                if event.done:
                    if wire_event.get("type") != "done":
                        raise ConfidentialOpenAIError("Protected stream final framing mismatch", status=502)
                    done_seen = True
                elif wire_event.get("type") != "chunk":
                    raise ConfidentialOpenAIError("Protected stream chunk framing mismatch", status=502)
                yield openai_sse_bytes(event)
            if not done_seen:
                raise ConfidentialOpenAIError("Protected stream ended before authenticated completion", status=502)
        finally:
            client_context.close()
