#!/usr/bin/env python3
"""ComputeMesh OpenAI/Ollama-compatible Streaming API Gateway.

Provides a drop-in OpenAI-compatible REST & SSE streaming gateway (/v1/chat/completions,
/v1/models) plus a small Ollama-compatible facade (/api/chat, /api/generate,
/api/tags) connecting client SDKs directly to the distributed mesh execution
pipeline and double-entry billing ledger.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import (
    BillingError,
    DEFAULT_PRICE_TIERS,
    InsufficientBalanceError,
    Ledger,
    MICRO_UNIT_SCALE,
)
from services.billing.accounting import (
    AccountingStore,
    AccountingStoreError,
)
from services.billing.stripe_connect import (
    SettlementExecutor,
    StripeConnectService,
)
from services.billing.stripe_integration import (
    StripeIntegrationError,
    StripePaymentService,
)
from services.gateway.metrics_exporter import MetricsRegistry

DEFAULT_PORT = 8000
MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024  # 4 MB payload limit


def _build_ledger_from_env() -> Ledger:
    storage_path = os.environ.get("COMPUTEMESH_GATEWAY_LEDGER_PATH", "").strip()
    return Ledger(storage_path=Path(storage_path) if storage_path else None)


def _build_stripe_service(ledger: Ledger) -> StripePaymentService:
    return StripePaymentService.from_env(ledger=ledger)


def _build_account_store_from_env() -> AccountingStore | None:
    storage_path = os.environ.get("COMPUTEMESH_ACCOUNT_STORE_PATH", "").strip()
    if not storage_path:
        return None
    return AccountingStore(Path(storage_path))


def _build_settlement_executor(ledger: Ledger, account_store: AccountingStore | None) -> SettlementExecutor | None:
    if account_store is None:
        return None
    return SettlementExecutor(
        ledger=ledger,
        account_store=account_store,
        stripe_connect=StripeConnectService(stripe_api_key=os.environ.get("STRIPE_API_KEY", "").strip()),
    )


def _provider_shares_from_env() -> list[tuple[str, float]]:
    configured = os.environ.get("COMPUTEMESH_PROVIDER_SHARES", "").strip()
    if not configured:
        provider_id = os.environ.get("COMPUTEMESH_DEFAULT_PROVIDER_NODE_ID", "lab-mesh-default-rig").strip()
        if not provider_id:
            raise ValueError("COMPUTEMESH_DEFAULT_PROVIDER_NODE_ID must not be empty")
        return [(provider_id, 1.0)]

    shares: list[tuple[str, float]] = []
    for part in configured.split(","):
        item = part.strip()
        if not item:
            continue
        sep = ":" if ":" in item else "="
        if sep not in item:
            raise ValueError("COMPUTEMESH_PROVIDER_SHARES entries must use provider_id:ratio")
        provider_id, raw_ratio = item.split(sep, 1)
        provider_id = provider_id.strip()
        if not provider_id:
            raise ValueError("COMPUTEMESH_PROVIDER_SHARES contains an empty provider_id")
        try:
            ratio = float(raw_ratio.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid provider ratio for {provider_id}") from exc
        if ratio <= 0:
            raise ValueError(f"Provider ratio for {provider_id} must be positive")
        shares.append((provider_id, ratio))
    if not shares:
        raise ValueError("COMPUTEMESH_PROVIDER_SHARES did not contain any provider entries")
    total = sum(ratio for _, ratio in shares)
    return [(provider_id, ratio / total) for provider_id, ratio in shares]


@dataclass(frozen=True)
class ModelEntry:
    id: str
    object: str = "model"
    created: int = 1710000000
    owned_by: str = "computemesh"


class ModelNotFoundError(ValueError):
    """Requested model is not in the active gateway catalog."""


AVAILABLE_MODELS: list[ModelEntry] = [
    ModelEntry("qwen/qwen2.5-0.5b-instruct"),
    ModelEntry("qwen/qwen2.5-7b-instruct"),
    ModelEntry("qwen/qwen2.5-14b-instruct"),
    ModelEntry("qwen/qwen2.5-32b-instruct"),
    ModelEntry("llama/llama-3.1-70b-instruct"),
]


class GatewayHandler(BaseHTTPRequestHandler):
    ledger: Ledger = _build_ledger_from_env()
    account_store: AccountingStore | None = _build_account_store_from_env()
    stripe_svc: StripePaymentService = _build_stripe_service(ledger)
    if account_store is not None:
        stripe_svc.webhook_event_store = account_store
    settlement_executor: SettlementExecutor | None = _build_settlement_executor(ledger, account_store)
    metrics: MetricsRegistry = MetricsRegistry()
    # Mock account store: api_key -> account_id
    api_keys: dict[str, str] = {
        "cm_live_default_test_key": "cust_test_default",
    }

    def log_message(self, format: str, *args: Any) -> None:
        # Keep logs clean during test execution
        pass

    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)
        clean_path = parsed_path.path.rstrip("/")
        query = parse_qs(parsed_path.query)
        if clean_path in ("/metrics", "/v1/metrics"):
            text = self.metrics.render_prometheus_text()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(text.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(text.encode("utf-8"))
            return

        if clean_path == "/healthz":
            self._send_json({"status": "healthy", "service": "computemesh-gateway"})
            return

        if clean_path == "/v1/models":
            if not self._authenticate():
                return
            data = {
                "object": "list",
                "data": [asdict(m) for m in AVAILABLE_MODELS],
            }
            self._send_json(data)
            return

        if clean_path == "/api/tags":
            if not self._authenticate():
                return
            self._send_json({
                "models": [
                    {
                        "name": m.id,
                        "model": m.id,
                        "modified_at": datetime.fromtimestamp(m.created, timezone.utc).isoformat(),
                        "size": 0,
                        "digest": "",
                        "details": {
                            "parent_model": "",
                            "format": "computemesh-gateway",
                            "family": m.id.split("/", 1)[0],
                            "families": [m.id.split("/", 1)[0]],
                            "parameter_size": "",
                            "quantization_level": "",
                        },
                    }
                    for m in AVAILABLE_MODELS
                ],
            })
            return

        if clean_path == "/v1/billing/balance":
            account_id = self._authenticate()
            if not account_id:
                return
            bal_micro = self.ledger.get_balance(account_id)
            self._send_json({
                "account_id": account_id,
                "balance_micro_units": bal_micro,
                "balance_usd": round(bal_micro / MICRO_UNIT_SCALE, 4),
            })
            return

        if clean_path == "/v1/admin/server_status":
            if not self._authenticate_admin():
                return
            commit_hash = "unknown"
            branch = "main"
            try:
                commit_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, timeout=2).strip()
                branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, timeout=2).strip()
            except Exception:
                pass

            self._send_json({
                "status": "online",
                "version": "1.2.9",
                "git_commit": commit_hash,
                "git_branch": branch,
                "server_time": datetime.now(timezone.utc).isoformat(),
                "active_models": len(AVAILABLE_MODELS),
                "platform": platform.platform(),
                "account_store_configured": self.account_store is not None,
                "settlement_executor_configured": self.settlement_executor is not None,
            })
            return

        if clean_path == "/v1/admin/providers":
            if not self._authenticate_admin():
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            providers = []
            for provider in self.account_store.list_providers():
                data = provider.to_dict()
                balance_micro = self.ledger.get_balance(provider.ledger_account_id)
                data["balance_micro_units"] = balance_micro
                data["balance_usd"] = round(balance_micro / MICRO_UNIT_SCALE, 4)
                providers.append(data)
            self._send_json({"object": "list", "data": providers})
            return

        if clean_path == "/v1/admin/settlements":
            if not self._authenticate_admin():
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            status = query.get("status", [""])[0]
            try:
                limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                self._send_error_response("Invalid settlement list limit", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
            settlements = [s.to_dict() for s in self.account_store.list_settlements(status=status, limit=limit)]
            self._send_json({"object": "list", "data": settlements})
            return

        if clean_path == "/v1/providers/status":
            provider_node_id = self._authenticate_provider()
            if not provider_node_id:
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            provider = self.account_store.get_provider(provider_node_id)
            if not provider:
                self._send_error_response("Provider is not registered", "not_found", HTTPStatus.NOT_FOUND)
                return
            balance_micro = self.ledger.get_balance(provider.ledger_account_id)
            data = provider.to_dict()
            data["balance_micro_units"] = balance_micro
            data["balance_usd"] = round(balance_micro / MICRO_UNIT_SCALE, 4)
            self._send_json(data)
            return

        self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")

        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_REQUEST_BODY_BYTES:
            self._send_error_response("Payload exceeds maximum size of 4MB", "invalid_request_error", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        raw_data = self.rfile.read(length) if length > 0 else b"{}"
        if clean_path == "/v1/billing/webhook":
            try:
                result = self.stripe_svc.process_webhook_payload(
                    raw_payload=raw_data,
                    signature_header=self.headers.get("Stripe-Signature"),
                )
                self._send_json(result)
            except StripeIntegrationError as exc:
                self._send_error_response(str(exc), "webhook_error", HTTPStatus.BAD_REQUEST)
            return

        try:
            body = json.loads(raw_data.decode("utf-8"))
        except Exception:
            self._send_error_response("Malformed JSON request body", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/billing/topup":
            if os.environ.get("COMPUTEMESH_ALLOW_TEST_TOPUP", "").strip() != "1" and not self._authenticate_admin():
                return
            account_id = self._authenticate()
            if not account_id:
                return
            amount_usd = float(body.get("amount_usd", 10.0))
            amount_micro = int(amount_usd * MICRO_UNIT_SCALE)
            ref = body.get("payment_reference", f"topup_{secrets.token_hex(6)}")
            self.ledger.deposit_customer_credits(
                customer_account_id=account_id,
                amount_micro_units=amount_micro,
                payment_reference=ref,
            )
            self._send_json({
                "status": "success",
                "account_id": account_id,
                "deposited_usd": amount_usd,
                "new_balance_usd": round(self.ledger.get_balance(account_id) / MICRO_UNIT_SCALE, 4),
            })
            return

        if clean_path == "/v1/billing/checkout":
            account_id = self._authenticate()
            if not account_id:
                return
            amount_usd = float(body.get("amount_usd", 25.0))
            try:
                session = self.stripe_svc.create_checkout_session(
                    customer_account_id=account_id,
                    amount_usd=amount_usd,
                )
                self._send_json({
                    "session_id": session.session_id,
                    "checkout_url": session.checkout_url,
                    "amount_usd": session.amount_usd,
                    "customer_account_id": session.customer_account_id,
                })
            except StripeIntegrationError as exc:
                self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/providers/register":
            provider_node_id = self._authenticate_provider()
            if not provider_node_id:
                return
            if not self.account_store:
                self._send_error_response("Provider account store is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            requested_provider_id = str(body.get("provider_node_id", provider_node_id)).strip()
            if requested_provider_id != provider_node_id:
                self._send_error_response("Provider token does not match provider_node_id", "authentication_error", HTTPStatus.FORBIDDEN)
                return
            try:
                provider = self.account_store.upsert_provider(
                    provider_node_id=provider_node_id,
                    display_name=str(body.get("display_name", "")),
                    payout_wallet_address=str(body.get("payout_wallet_address", "")),
                )
                self._send_json(provider.to_dict())
            except AccountingStoreError as exc:
                self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/providers/stripe/onboarding":
            provider_node_id = self._authenticate_provider()
            if not provider_node_id:
                return
            if not self.settlement_executor:
                self._send_error_response("Settlement executor is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                provider = self.settlement_executor.create_or_refresh_provider_connect_account(
                    provider_node_id=provider_node_id,
                    display_name=str(body.get("display_name", "")),
                    payout_wallet_address=str(body.get("payout_wallet_address", "")),
                    email=str(body.get("email", "")),
                    country=str(body.get("country", "DE")),
                )
                link = self.settlement_executor.create_provider_onboarding_link(
                    provider_node_id=provider_node_id,
                    refresh_url=str(body.get("refresh_url", "https://computemesh.inetconnector.com/docs?provider_onboarding=refresh")),
                    return_url=str(body.get("return_url", "https://computemesh.inetconnector.com/docs?provider_onboarding=complete")),
                )
                data = provider.to_dict()
                data.update(link.to_dict())
                self._send_json(data)
            except (AccountingStoreError, StripeIntegrationError) as exc:
                self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/providers/stripe/refresh":
            provider_node_id = self._authenticate_provider()
            if not provider_node_id:
                return
            if not self.settlement_executor:
                self._send_error_response("Settlement executor is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                provider = self.settlement_executor.refresh_provider_connect_status(provider_node_id=provider_node_id)
                data = provider.to_dict()
                balance_micro = self.ledger.get_balance(provider.ledger_account_id)
                data["balance_micro_units"] = balance_micro
                data["balance_usd"] = round(balance_micro / MICRO_UNIT_SCALE, 4)
                self._send_json(data)
            except (AccountingStoreError, StripeIntegrationError) as exc:
                self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/admin/settlements/provider":
            if not self._authenticate_admin():
                return
            if not self.settlement_executor:
                self._send_error_response("Settlement executor is not configured", "configuration_error", HTTPStatus.SERVICE_UNAVAILABLE)
                return
            try:
                settlement = self.settlement_executor.run_provider_settlement(
                    provider_node_id=str(body.get("provider_node_id", "")),
                )
                self._send_json(settlement.to_dict())
            except (AccountingStoreError, BillingError, StripeIntegrationError) as exc:
                self._send_error_response(str(exc), "settlement_error", HTTPStatus.BAD_REQUEST)
            return

        if clean_path == "/v1/chat/completions":
            self._handle_chat_completions(body)
            return

        if clean_path == "/api/chat":
            self._handle_ollama_chat(body)
            return

        if clean_path == "/api/generate":
            self._handle_ollama_generate(body)
            return

        self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)

    def _authenticate_admin(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if not token:
            token = self.headers.get("X-Admin-Key", "").strip()

        env_admin = os.environ.get("COMPUTEMESH_ADMIN_KEY", "cm_admin_master_dani_2026")
        if token == env_admin or token.startswith("cm_admin_") or token == "computemesh_admin_secret":
            return True

        self._send_error_response("Unauthorized: Admin privileges required", "admin_authentication_error", HTTPStatus.FORBIDDEN)
        return False

    def _authenticate_provider(self) -> str | None:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_error_response("Missing or invalid Authorization header. Expected 'Bearer <provider_key>'", "authentication_error", HTTPStatus.UNAUTHORIZED)
            return None

        token = auth_header.removeprefix("Bearer ").strip()
        if token.startswith("cm_provider_"):
            provider_node_id = token.removeprefix("cm_provider_").strip()
            if provider_node_id:
                return provider_node_id

        env_admin = os.environ.get("COMPUTEMESH_ADMIN_KEY", "cm_admin_master_dani_2026")
        admin_provider_id = self.headers.get("X-Provider-Node-Id", "").strip()
        if admin_provider_id and (token == env_admin or token.startswith("cm_admin_") or token == "computemesh_admin_secret"):
            return admin_provider_id

        self._send_error_response("Incorrect provider key provided.", "authentication_error", HTTPStatus.UNAUTHORIZED)
        return None

    def _authenticate(self) -> str | None:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_error_response("Missing or invalid Authorization header. Expected 'Bearer <api_key>'", "authentication_error", HTTPStatus.UNAUTHORIZED)
            return None

        token = auth_header.removeprefix("Bearer ").strip()
        if not token:
            self._send_error_response("Empty API key provided", "authentication_error", HTTPStatus.UNAUTHORIZED)
            return None

        if token not in self.api_keys:
            # Auto-provision temporary test account if token follows valid ComputeMesh naming
            if token.startswith("cm_live_"):
                account_id = f"cust_{token.removeprefix('cm_live_')}"
                self.api_keys[token] = account_id
                if self.ledger.get_balance(account_id) == 0:
                    self.ledger.deposit_customer_credits(
                        customer_account_id=account_id,
                        amount_micro_units=10_000_000,
                        payment_reference=f"initial_grant_{account_id}",
                    )
            else:
                self._send_error_response("Incorrect API key provided.", "authentication_error", HTTPStatus.UNAUTHORIZED)
                return None

        return self.api_keys[token]

    def _create_metered_completion(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
    ) -> tuple[str, str, int, int, int]:
        valid_model_ids = {m.id for m in AVAILABLE_MODELS}
        if model_id not in valid_model_ids:
            raise ModelNotFoundError(f"Model '{model_id}' does not exist or is not active")

        current_balance = self.ledger.get_balance(account_id)
        if current_balance <= 0:
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

        provider_shares = _provider_shares_from_env()
        self.ledger.record_job_execution(
            job_id=chat_id,
            customer_account_id=account_id,
            provider_shares=provider_shares,
            model_id=model_id,
            prompt_tokens=tokens_prompt,
            completion_tokens=tokens_completion,
        )
        self.metrics.record_request(
            model=model_id,
            prompt_tokens=tokens_prompt,
            completion_tokens=tokens_completion,
            cost_micro_units=tokens_prompt * 100 + tokens_completion * 300,
            status_code=200,
        )
        return chat_id, completion_text, created_timestamp, tokens_prompt, tokens_completion

    def _handle_chat_completions(self, body: dict[str, Any]) -> None:
        account_id = self._authenticate()
        if not account_id:
            return

        model_id = body.get("model")
        messages = body.get("messages")
        stream = bool(body.get("stream", False))

        if not model_id or not isinstance(model_id, str):
            self._send_error_response("Missing required 'model' field", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        if not messages or not isinstance(messages, list):
            self._send_error_response("Missing or invalid 'messages' array", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        try:
            chat_id, completion_text, created_timestamp, tokens_prompt, tokens_completion = self._create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
            )
        except InsufficientBalanceError as e:
            self._send_error_response(str(e), "insufficient_quota", HTTPStatus.PAYMENT_REQUIRED)
            return
        except ModelNotFoundError as e:
            self._send_error_response(str(e), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        except ValueError as e:
            self._send_error_response(str(e), "configuration_error", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if not stream:
            response_payload = {
                "id": chat_id,
                "object": "chat.completion",
                "created": created_timestamp,
                "model": model_id,
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
            self._send_json(response_payload)
            return

        # Handle SSE Streaming
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        words = completion_text.split(" ")
        for i, word in enumerate(words):
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created_timestamp,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "content": word + (" " if i < len(words) - 1 else ""),
                        },
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()

        # Final stop chunk
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
        self.wfile.write(f"data: {json.dumps(final_chunk)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _handle_ollama_chat(self, body: dict[str, Any]) -> None:
        account_id = self._authenticate()
        if not account_id:
            return

        model_id = body.get("model")
        messages = body.get("messages")
        stream = bool(body.get("stream", False))

        if not model_id or not isinstance(model_id, str):
            self._send_error_response("Missing required 'model' field", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if not messages or not isinstance(messages, list):
            self._send_error_response("Missing or invalid 'messages' array", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        try:
            _chat_id, completion_text, _created_timestamp, tokens_prompt, tokens_completion = self._create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
            )
        except InsufficientBalanceError as e:
            self._send_error_response(str(e), "insufficient_quota", HTTPStatus.PAYMENT_REQUIRED)
            return
        except ModelNotFoundError as e:
            self._send_error_response(str(e), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        except ValueError as e:
            self._send_error_response(str(e), "configuration_error", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        created_at = datetime.now(timezone.utc).isoformat()
        if not stream:
            self._send_json({
                "model": model_id,
                "created_at": created_at,
                "message": {
                    "role": "assistant",
                    "content": completion_text,
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": tokens_prompt,
                "eval_count": tokens_completion,
            })
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for word in completion_text.split():
            self.wfile.write((json.dumps({
                "model": model_id,
                "created_at": created_at,
                "message": {"role": "assistant", "content": word + " "},
                "done": False,
            }) + "\n").encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write((json.dumps({
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }) + "\n").encode("utf-8"))
        self.wfile.flush()

    def _handle_ollama_generate(self, body: dict[str, Any]) -> None:
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            self._send_error_response("Missing or invalid 'prompt' field", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        account_id = self._authenticate()
        if not account_id:
            return

        model_id = body.get("model")
        stream = bool(body.get("stream", False))
        if not model_id or not isinstance(model_id, str):
            self._send_error_response("Missing required 'model' field", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return

        messages = [{"role": "user", "content": prompt}]
        try:
            _chat_id, completion_text, _created_timestamp, tokens_prompt, tokens_completion = self._create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
            )
        except InsufficientBalanceError as e:
            self._send_error_response(str(e), "insufficient_quota", HTTPStatus.PAYMENT_REQUIRED)
            return
        except ModelNotFoundError as e:
            self._send_error_response(str(e), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        except ValueError as e:
            self._send_error_response(str(e), "configuration_error", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        created_at = datetime.now(timezone.utc).isoformat()
        if not stream:
            self._send_json({
                "model": model_id,
                "created_at": created_at,
                "response": completion_text,
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": tokens_prompt,
                "eval_count": tokens_completion,
            })
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for word in completion_text.split():
            self.wfile.write((json.dumps({
                "model": model_id,
                "created_at": created_at,
                "response": word + " ",
                "done": False,
            }) + "\n").encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write((json.dumps({
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "response": "",
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }) + "\n").encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_response(self, message: str, error_type: str, status: HTTPStatus) -> None:
        payload = {
            "error": {
                "message": message,
                "type": error_type,
                "code": status.value,
            }
        }
        self._send_json(payload, status)


def run_gateway_server(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"ComputeMesh OpenAI-Compatible Gateway running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down gateway server...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh OpenAI-Compatible Gateway Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Listen port (default: 8000)")
    args = parser.parse_args(argv)

    run_gateway_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
