"""ComputeMesh Distributed Inference Engine.

Handles OpenAI-compatible and Ollama-compatible request execution, metering,
and multi-format streaming generation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Generator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import InsufficientBalanceError, Ledger
from services.common.config import CONFIG
from services.gateway.catalog import (
    AVAILABLE_MODELS,
    DEFAULT_PRICE_TIERS,
    calculate_max_charge_micro,
    calculate_token_charge_micro,
    provider_shares_from_env,
    resolve_model_id,
)
from services.gateway.inference_backend import (
    InferenceBackend,
    InferenceBackendError,
    build_inference_backend_from_env,
)
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.security import sanitize_error_message
from services.gateway.teaser import TeaserQuotaManager


class InferenceEngine:
    """Executes metered inference, performs quota tracking, and formats responses."""

    def __init__(
        self,
        ledger: Ledger,
        metrics: MetricsRegistry,
        teaser_manager: TeaserQuotaManager,
        backend: InferenceBackend | None = None,
    ) -> None:
        self.ledger = ledger
        self.metrics = metrics
        self.teaser_manager = teaser_manager
        self.backend = backend if backend is not None else build_inference_backend_from_env()

    def create_metered_completion(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        client_ip: str = "127.0.0.1",
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
    ) -> tuple[str, str, int, int, int]:
        """Execute inference first, then meter only a successful backend result.

        Returns: (chat_id, completion_text, created_timestamp, tokens_prompt, tokens_completion)
        """
        canonical_model_id = resolve_model_id(model_id)

        current_balance = self.ledger.get_balance(account_id)
        if not is_teaser and not is_provider_self_compute:
            est_prompt_tokens = sum(len(str(m.get("content", "")).split()) * 2 for m in messages if isinstance(m, dict)) or 64
            min_required_hold = calculate_max_charge_micro(canonical_model_id, est_prompt_tokens, 128)
            if current_balance < min_required_hold:
                raise InsufficientBalanceError(
                    f"Insufficient credits for compute reservation (balance: {current_balance} µ$, required minimum: {min_required_hold} µ$). Please top up."
                )

        # Billing must never precede execution. A failed or malformed runtime response
        # is not a billable job and therefore cannot credit a provider.
        backend_result = self.backend.complete(
            model_id=canonical_model_id,
            messages=messages,
        )
        completion_text = backend_result.text
        tokens_prompt = backend_result.prompt_tokens
        tokens_completion = backend_result.completion_tokens

        chat_id = f"chatcmpl-{secrets.token_hex(12)}"
        created_timestamp = int(time.time())

        if is_teaser:
            sess = self.teaser_manager.record_usage(client_ip, tokens=tokens_prompt + tokens_completion)
            rem = sess.remaining_requests
            max_req = self.teaser_manager.max_requests
            completion_text += f"\n\n---\n*⚡ ComputeMesh Free Teaser: Noch {rem}/{max_req} Anfragen übrig | {CONFIG.endpoints.domain}*"

        # Verified orchestrated execution takes precedence over operator-configured
        # shares. The ledger event also uses the durable orchestrator job id so the
        # financial event can be traced back to its reservation/evidence record.
        provider_shares = (
            list(backend_result.provider_shares)
            if backend_result.provider_shares is not None
            else provider_shares_from_env()
        )
        billing_job_id = backend_result.execution_job_id or chat_id
        fee_bps = 0 if is_provider_self_compute else None

        self.ledger.record_job_execution(
            job_id=billing_job_id,
            customer_account_id=account_id,
            provider_shares=provider_shares,
            model_id=canonical_model_id,
            prompt_tokens=tokens_prompt,
            completion_tokens=tokens_completion,
            network_fee_bps=fee_bps,
        )

        cost_micro = calculate_token_charge_micro(
            model_id=canonical_model_id,
            prompt_tokens=tokens_prompt,
            completion_tokens=tokens_completion,
        )
        self.metrics.record_request(
            model=canonical_model_id,
            prompt_tokens=tokens_prompt,
            completion_tokens=tokens_completion,
            cost_micro_units=cost_micro,
            status_code=200,
        )
        return chat_id, completion_text, created_timestamp, tokens_prompt, tokens_completion

    @staticmethod
    def format_openai_response(
        *,
        chat_id: str,
        model_id: str,
        completion_text: str,
        created_timestamp: int,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> dict[str, Any]:
        """Formats standard OpenAI chat completion JSON response."""
        return {
            "id": chat_id,
            "object": "chat.completion",
            "created": created_timestamp,
            "model": model_id if isinstance(model_id, str) else "computemesh",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": completion_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": tokens_prompt,
                "completion_tokens": tokens_completion,
                "total_tokens": tokens_prompt + tokens_completion,
            },
        }

    @staticmethod
    def stream_openai_sse(
        *,
        chat_id: str,
        model_id: str,
        completion_text: str,
        created_timestamp: int,
    ) -> Generator[bytes, None, None]:
        """Yields Server-Sent Events (SSE) stream chunks for OpenAI clients."""
        words = completion_text.split(" ")
        for i, word in enumerate(words):
            token_str = word + (" " if i < len(words) - 1 else "")
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created_timestamp,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": token_str},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
            time.sleep(0.01)

        final_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created_timestamp,
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_chunk)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"

    @staticmethod
    def format_ollama_chat_response(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> dict[str, Any]:
        """Formats non-streaming response for Ollama /api/chat."""
        return {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": {
                "role": "assistant",
                "content": completion_text,
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }

    @staticmethod
    def stream_ollama_chat_ndjson(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> Generator[bytes, None, None]:
        """Yields newline-delimited JSON stream chunks for Ollama /api/chat."""
        words = completion_text.split(" ")
        for i, word in enumerate(words):
            token_str = word + (" " if i < len(words) - 1 else "")
            chunk = {
                "model": model_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "message": {"role": "assistant", "content": token_str},
                "done": False,
            }
            yield (json.dumps(chunk) + "\n").encode("utf-8")
            time.sleep(0.01)

        final_chunk = {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }
        yield (json.dumps(final_chunk) + "\n").encode("utf-8")

    @staticmethod
    def format_ollama_generate_response(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> dict[str, Any]:
        """Formats non-streaming response for Ollama /api/generate."""
        return {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "response": completion_text,
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }

    @staticmethod
    def stream_ollama_generate_ndjson(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> Generator[bytes, None, None]:
        """Yields newline-delimited JSON stream chunks for Ollama /api/generate."""
        words = completion_text.split(" ")
        for i, word in enumerate(words):
            token_str = word + (" " if i < len(words) - 1 else "")
            chunk = {
                "model": model_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "response": token_str,
                "done": False,
            }
            yield (json.dumps(chunk) + "\n").encode("utf-8")
            time.sleep(0.01)

        final_chunk = {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "response": "",
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }
        yield (json.dumps(final_chunk) + "\n").encode("utf-8")

    def execute_chat_completion(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> tuple[dict[str, Any] | None, str | None, int]:
        try:
            chat_id, completion_text, created_ts, tok_p, tok_c = self.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self_compute,
                client_ip=client_ip,
            )
            res = self.format_openai_response(
                chat_id=chat_id,
                model_id=model_id,
                completion_text=completion_text,
                created_timestamp=created_ts,
                tokens_prompt=tok_p,
                tokens_completion=tok_c,
            )
            return (res, None, 200)
        except InsufficientBalanceError as exc:
            return (None, str(exc), 402)
        except InferenceBackendError as exc:
            return (None, sanitize_error_message(exc), 503)
        except Exception as exc:
            return (None, sanitize_error_message(exc), 500)

    def stream_chat_completions(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> Generator[bytes, None, None]:
        chat_id, completion_text, created_ts, _, _ = self.create_metered_completion(
            account_id=account_id,
            model_id=model_id,
            messages=messages,
            is_teaser=is_teaser,
            is_provider_self_compute=is_provider_self_compute,
            client_ip=client_ip,
        )
        yield from self.stream_openai_sse(
            chat_id=chat_id,
            model_id=model_id,
            completion_text=completion_text,
            created_timestamp=created_ts,
        )

    def execute_ollama_chat(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> tuple[dict[str, Any] | None, str | None, int]:
        try:
            _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self_compute,
                client_ip=client_ip,
            )
            res = self.format_ollama_chat_response(
                model_id=model_id,
                completion_text=completion_text,
                tokens_prompt=tok_p,
                tokens_completion=tok_c,
            )
            return (res, None, 200)
        except InsufficientBalanceError as exc:
            return (None, sanitize_error_message(exc), 402)
        except InferenceBackendError as exc:
            return (None, sanitize_error_message(exc), 503)
        except Exception as exc:
            return (None, sanitize_error_message(exc), 500)

    def stream_ollama_chat(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> Generator[bytes, None, None]:
        _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
            account_id=account_id,
            model_id=model_id,
            messages=messages,
            is_teaser=is_teaser,
            is_provider_self_compute=is_provider_self_compute,
            client_ip=client_ip,
        )
        yield from self.stream_ollama_chat_ndjson(
            model_id=model_id,
            completion_text=completion_text,
            tokens_prompt=tok_p,
            tokens_completion=tok_c,
        )

    def execute_ollama_generate(
        self,
        *,
        account_id: str,
        model_id: str,
        prompt: str,
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> tuple[dict[str, Any] | None, str | None, int]:
        messages = [{"role": "user", "content": prompt}]
        try:
            _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self_compute,
                client_ip=client_ip,
            )
            res = self.format_ollama_generate_response(
                model_id=model_id,
                completion_text=completion_text,
                tokens_prompt=tok_p,
                tokens_completion=tok_c,
            )
            return (res, None, 200)
        except InsufficientBalanceError as exc:
            return (None, sanitize_error_message(exc), 402)
        except InferenceBackendError as exc:
            return (None, sanitize_error_message(exc), 503)
        except Exception as exc:
            return (None, sanitize_error_message(exc), 500)

    def stream_ollama_generate(
        self,
        *,
        account_id: str,
        model_id: str,
        prompt: str,
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
    ) -> Generator[bytes, None, None]:
        messages = [{"role": "user", "content": prompt}]
        _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
            account_id=account_id,
            model_id=model_id,
            messages=messages,
            is_teaser=is_teaser,
            is_provider_self_compute=is_provider_self_compute,
            client_ip=client_ip,
        )
        yield from self.stream_ollama_generate_ndjson(
            model_id=model_id,
            completion_text=completion_text,
            tokens_prompt=tok_p,
            tokens_completion=tok_c,
        )
