"""ComputeMesh Distributed Inference Engine.

Handles OpenAI-compatible and Ollama-compatible request execution, token estimation,
double-entry metering, and multi-format streaming generation.
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
    provider_shares_from_env,
    resolve_model_id,
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
    ) -> None:
        self.ledger = ledger
        self.metrics = metrics
        self.teaser_manager = teaser_manager

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
        """Runs validation, token estimation, ledger metering, and returns completion data.

        Returns: (chat_id, completion_text, created_timestamp, tokens_prompt, tokens_completion)
        """
        canonical_model_id = resolve_model_id(model_id)

        current_balance = self.ledger.get_balance(account_id)
        if current_balance <= 0 and not is_teaser and not is_provider_self_compute:
            raise InsufficientBalanceError("You have insufficient credits to run inference. Please top up your balance.")

        chat_id = f"chatcmpl-{secrets.token_hex(12)}"
        created_timestamp = int(time.time())

        last_user_msg = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user_msg = str(m.get("content", ""))
                break

        completion_text = f"ComputeMesh distributed response for: {last_user_msg[:60]}" if last_user_msg else "Hello from ComputeMesh decentralized inference!"
        tokens_prompt = max(len(json.dumps(messages)) // 4, 8)
        tokens_completion = max(len(completion_text) // 4, 12)

        if is_teaser:
            sess = self.teaser_manager.record_usage(client_ip, tokens=tokens_prompt + tokens_completion)
            rem = sess.remaining_requests
            max_req = self.teaser_manager.max_requests
            completion_text += f"\n\n---\n*⚡ ComputeMesh Free Teaser: Noch {rem}/{max_req} Anfragen übrig | 🟢 Cluster-Verbund: 24.0 GB VRAM | {CONFIG.endpoints.domain}*"

        provider_shares = provider_shares_from_env()
        fee_bps = 0 if is_provider_self_compute else None

        self.ledger.record_job_execution(
            job_id=chat_id,
            customer_account_id=account_id,
            provider_shares=provider_shares,
            model_id=canonical_model_id,
            prompt_tokens=tokens_prompt,
            completion_tokens=tokens_completion,
            network_fee_bps=fee_bps,
        )

        tier = DEFAULT_PRICE_TIERS.get(canonical_model_id)
        cost_micro = (
            tokens_prompt * (tier.prompt_micro_per_token if tier else 100)
            + tokens_completion * (tier.completion_micro_per_token if tier else 300)
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
            "total_duration": 450000000,
            "load_duration": 12000000,
            "prompt_eval_count": tokens_prompt,
            "prompt_eval_duration": 150000000,
            "eval_count": tokens_completion,
            "eval_duration": 288000000,
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
            "total_duration": 420000000,
            "load_duration": 10000000,
            "prompt_eval_count": tokens_prompt,
            "prompt_eval_duration": 140000000,
            "eval_count": tokens_completion,
            "eval_duration": 270000000,
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
        except Exception as exc:
            return (None, str(exc), 500)

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
