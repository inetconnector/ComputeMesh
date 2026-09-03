"""Private-policy confidential admission with local authenticated provider dispatch.

The private control plane receives only content-free live candidates and returns one
short-lived signed dispatch decision. The public gateway verifies that decision and
uses its existing Ed25519-authenticated persistent NodeSession to ask exactly that
provider for fresh hardware attestation and a protected endpoint. Candidate scores,
fraud/reputation features, and plaintext content never cross this boundary.
"""
from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import ssl
from typing import Any, Mapping
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from runtime.confidential.data_plane import AttestedConfidentialEndpoint
from runtime.confidential.protected_worker import CONFIDENTIAL_PROVISION_CAPABILITY
from runtime.confidential.provider_control import CONFIDENTIAL_PROVISION_MESSAGE
from runtime.confidential.session import ConfidentialSessionError, ConfidentialSessionProvision
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry
from services.orchestrator.persistent_control_channel import PersistentControlChannelError


MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_PATH = "/internal/v1/confidential/dispatch"
RELEASE_PATH = "/internal/v1/confidential/release"


class RemoteConfidentialBrokerError(ConfidentialSessionError):
    pass


def _b64u_decode(value: Any, expected_bytes: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise RemoteConfidentialBrokerError("confidential decision signature encoding is empty")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise RemoteConfidentialBrokerError("confidential decision signature is not base64url")
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError) as exc:
        raise RemoteConfidentialBrokerError("confidential decision signature is malformed") from exc
    if len(raw) != expected_bytes:
        raise RemoteConfidentialBrokerError("confidential decision signature has unexpected length")
    return raw


def _canonical_unsigned(value: Mapping[str, Any]) -> bytes:
    unsigned = dict(value)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class RemoteConfidentialSessionBroker:
    """Fail-closed broker spanning private selection and the live provider channel."""

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        verification_key_b64u: str,
        expected_key_id: str,
        registry: LiveSharedRuntimeRegistry,
        ca_file: Path | str | None = None,
        timeout_seconds: float = 10.0,
        provider_timeout_seconds: float = 20.0,
    ) -> None:
        parsed = urlparse.urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("confidential control-plane endpoint must use HTTPS")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError("confidential control-plane endpoint contains forbidden components")
        if not parsed.path or parsed.path == "/":
            parsed = parsed._replace(path=DEFAULT_PATH)
        self.endpoint = urlparse.urlunparse(parsed)
        self.release_endpoint = urlparse.urlunparse(parsed._replace(path=RELEASE_PATH))
        if not bearer_token or len(bearer_token) > 4096:
            raise ValueError("confidential control-plane bearer token is invalid")
        if not expected_key_id or len(expected_key_id) > 256:
            raise ValueError("confidential decision signing key id is invalid")
        if not 0.5 <= float(timeout_seconds) <= 120.0:
            raise ValueError("confidential control-plane timeout must be between 0.5 and 120 seconds")
        if not 0.5 <= float(provider_timeout_seconds) <= 120.0:
            raise ValueError("confidential provider timeout must be between 0.5 and 120 seconds")
        try:
            self.verification_key = Ed25519PublicKey.from_public_bytes(_b64u_decode(verification_key_b64u, 32))
        except RemoteConfidentialBrokerError as exc:
            raise ValueError("confidential decision verification key is invalid") from exc
        self.expected_key_id = expected_key_id
        self.registry = registry
        self.bearer_token = bearer_token
        self.timeout_seconds = float(timeout_seconds)
        self.provider_timeout_seconds = float(provider_timeout_seconds)
        self.ssl_context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    @staticmethod
    def _parse_provision(value: Mapping[str, Any]) -> ConfidentialSessionProvision:
        required = {
            "schema_version",
            "job_id",
            "account_id",
            "model_id",
            "privacy_class",
            "operation",
            "max_prompt_tokens",
            "max_completion_tokens",
            "expires_at",
            "endpoint",
            "attestation",
        }
        if set(value) != required or value.get("schema_version") != 1:
            raise RemoteConfidentialBrokerError("invalid confidential provision response")
        endpoint_value = value.get("endpoint")
        attestation = value.get("attestation")
        if not isinstance(endpoint_value, Mapping) or not isinstance(attestation, Mapping):
            raise RemoteConfidentialBrokerError("invalid confidential provision evidence")
        endpoint_required = {
            "url",
            "node_id",
            "runtime_digest",
            "attestation_nonce",
            "recipient_public_key",
            "metering_public_key",
            "tls_certificate_sha256",
        }
        if set(endpoint_value) != endpoint_required:
            raise RemoteConfidentialBrokerError("invalid confidential endpoint response")
        provision = ConfidentialSessionProvision(
            job_id=value.get("job_id"),
            account_id=value.get("account_id"),
            model_id=value.get("model_id"),
            privacy_class=value.get("privacy_class"),
            operation=value.get("operation"),
            max_prompt_tokens=value.get("max_prompt_tokens"),
            max_completion_tokens=value.get("max_completion_tokens"),
            expires_at=value.get("expires_at"),
            endpoint=AttestedConfidentialEndpoint(
                url=endpoint_value.get("url"),
                node_id=endpoint_value.get("node_id"),
                runtime_digest=endpoint_value.get("runtime_digest"),
                attestation_nonce=endpoint_value.get("attestation_nonce"),
                recipient_public_key=endpoint_value.get("recipient_public_key"),
                metering_public_key=endpoint_value.get("metering_public_key"),
                tls_certificate_sha256=endpoint_value.get("tls_certificate_sha256"),
            ),
            attestation=dict(attestation),
        )
        provision.validate()
        return provision

    def _post(self, endpoint: str, body: Mapping[str, Any]) -> dict[str, Any]:
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urlrequest.Request(
            endpoint,
            data=raw,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Content-Length": str(len(raw)),
                "User-Agent": "ComputeMesh-Gateway/ProtectedBroker-2",
            },
        )
        try:
            with urlrequest.urlopen(request, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                response_raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(response.status)
        except urlerror.HTTPError as exc:
            raise RemoteConfidentialBrokerError(
                f"confidential control plane rejected admission with HTTP {exc.code}"
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            raise RemoteConfidentialBrokerError("confidential control plane is unavailable") from exc
        if status != 200 or len(response_raw) > MAX_RESPONSE_BYTES:
            raise RemoteConfidentialBrokerError("invalid confidential control-plane response")
        try:
            value = json.loads(response_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteConfidentialBrokerError("malformed confidential control-plane response") from exc
        if not isinstance(value, dict):
            raise RemoteConfidentialBrokerError("invalid confidential control-plane response")
        return value

    def _verify_decision(self, value: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "schema_version",
            "decision_type",
            "decision_id",
            "issued_at",
            "expires_at",
            "payload",
            "signature",
        }
        if set(value) != required or value.get("schema_version") != 1 or value.get("decision_type") != "confidential_dispatch":
            raise RemoteConfidentialBrokerError("private confidential decision envelope is invalid")
        signature = value.get("signature")
        if not isinstance(signature, Mapping):
            raise RemoteConfidentialBrokerError("private confidential decision is unsigned")
        if signature.get("algorithm") != "Ed25519" or signature.get("key_id") != self.expected_key_id:
            raise RemoteConfidentialBrokerError("private confidential decision uses an unexpected signing key")
        try:
            self.verification_key.verify(_b64u_decode(signature.get("value"), 64), _canonical_unsigned(value))
        except InvalidSignature as exc:
            raise RemoteConfidentialBrokerError("private confidential decision signature verification failed") from exc
        try:
            issued = datetime.fromisoformat(str(value["issued_at"]).replace("Z", "+00:00")).astimezone(UTC)
            expires = datetime.fromisoformat(str(value["expires_at"]).replace("Z", "+00:00")).astimezone(UTC)
        except (ValueError, TypeError) as exc:
            raise RemoteConfidentialBrokerError("private confidential decision timestamps are invalid") from exc
        now = datetime.now(UTC)
        if issued > now + timedelta(seconds=30) or expires <= now or expires > issued + timedelta(seconds=300):
            raise RemoteConfidentialBrokerError("private confidential decision freshness is invalid")
        payload = value.get("payload")
        if not isinstance(payload, dict):
            raise RemoteConfidentialBrokerError("private confidential decision payload is invalid")
        return payload

    def _live_candidates(self) -> tuple[tuple[str, Any], ...]:
        client = self.registry.control_client
        live_ids = getattr(client, "live_node_ids", None)
        if not callable(live_ids):
            raise RemoteConfidentialBrokerError("live node control client cannot enumerate confidential providers")
        candidates: list[tuple[str, Any]] = []
        try:
            node_ids = tuple(live_ids())
        except Exception as exc:
            raise RemoteConfidentialBrokerError("live confidential provider set is unavailable") from exc
        for node_id in node_ids:
            try:
                session = self.registry.get_session(node_id)
            except KeyError:
                continue
            if CONFIDENTIAL_PROVISION_CAPABILITY not in session.negotiated_capabilities:
                continue
            if not self.registry.is_node_control_healthy(node_id):
                continue
            candidates.append((node_id, session))
        candidates.sort(key=lambda item: item[0])
        if not candidates:
            raise RemoteConfidentialBrokerError("no authenticated confidential provider is live")
        return tuple(candidates)

    def _release_best_effort(self, decision_id: str) -> None:
        try:
            self._post(self.release_endpoint, {"schema_version": 1, "decision_id": decision_id})
        except Exception:
            pass

    def provision(
        self,
        *,
        account_id: str,
        model_id: str,
        privacy_class: str,
        operation: str,
        max_prompt_tokens: int,
        max_completion_tokens: int,
    ) -> ConfidentialSessionProvision:
        if privacy_class != "CONFIDENTIAL":
            raise RemoteConfidentialBrokerError("remote protected broker currently accepts CONFIDENTIAL only")
        candidates = self._live_candidates()
        candidate_by_node = {node_id: session for node_id, session in candidates}
        admission_id = "confidential-admission-" + secrets.token_hex(16)
        request_body = {
            "schema_version": 1,
            "admission_id": admission_id,
            "account_id": account_id,
            "model_id": model_id,
            "privacy_class": privacy_class,
            "operation": operation,
            "max_prompt_tokens": max_prompt_tokens,
            "max_completion_tokens": max_completion_tokens,
            "candidates": [
                {
                    "node_id": node_id,
                    "session_id": session.session_id,
                    "session_revision": session.revision,
                }
                for node_id, session in candidates
            ],
        }
        decision = self._post(self.endpoint, request_body)
        payload = self._verify_decision(decision)
        expected_payload = {
            "admission_id",
            "job_id",
            "account_id",
            "model_id",
            "privacy_class",
            "operation",
            "max_prompt_tokens",
            "max_completion_tokens",
            "node_id",
            "session_id",
            "session_revision",
            "freshness_challenge",
        }
        if set(payload) != expected_payload:
            raise RemoteConfidentialBrokerError("private confidential dispatch payload has unexpected fields")
        for name, expected in (
            ("admission_id", admission_id),
            ("account_id", account_id),
            ("model_id", model_id),
            ("privacy_class", privacy_class),
            ("operation", operation),
            ("max_prompt_tokens", max_prompt_tokens),
            ("max_completion_tokens", max_completion_tokens),
        ):
            if payload.get(name) != expected:
                raise RemoteConfidentialBrokerError(f"private confidential decision changed {name}")
        node_id = payload.get("node_id")
        if not isinstance(node_id, str) or node_id not in candidate_by_node:
            raise RemoteConfidentialBrokerError("private confidential decision selected an unsubmitted node")
        session = candidate_by_node[node_id]
        if payload.get("session_id") != session.session_id or payload.get("session_revision") != session.revision:
            raise RemoteConfidentialBrokerError("private confidential decision selected a stale NodeSession")
        decision_id = decision.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id:
            raise RemoteConfidentialBrokerError("private confidential decision id is invalid")
        provider_request = {
            "session_id": session.session_id,
            "session_revision": session.revision,
            "freshness_challenge": payload.get("freshness_challenge"),
            "request": {
                "account_id": account_id,
                "job_id": payload.get("job_id"),
                "model_id": model_id,
                "privacy_class": privacy_class,
                "operation": operation,
                "max_prompt_tokens": max_prompt_tokens,
                "max_completion_tokens": max_completion_tokens,
            },
        }
        try:
            response = self.registry.control_client.request(
                node_id=node_id,
                message_type=CONFIDENTIAL_PROVISION_MESSAGE,
                payload=provider_request,
                timeout_seconds=self.provider_timeout_seconds,
            )
            if not isinstance(response, Mapping) or set(response) != {"session_id", "session_revision", "node_id", "provision"}:
                raise RemoteConfidentialBrokerError("provider returned an invalid confidential control response")
            if response.get("session_id") != session.session_id or response.get("session_revision") != session.revision:
                raise RemoteConfidentialBrokerError("provider returned a stale confidential NodeSession binding")
            if response.get("node_id") != node_id:
                raise RemoteConfidentialBrokerError("provider returned a different confidential node identity")
            provision_raw = response.get("provision")
            if not isinstance(provision_raw, Mapping):
                raise RemoteConfidentialBrokerError("provider confidential provision is missing")
            provision = self._parse_provision(provision_raw)
            for actual, expected, label in (
                (provision.job_id, payload.get("job_id"), "job_id"),
                (provision.account_id, account_id, "account_id"),
                (provision.model_id, model_id, "model_id"),
                (provision.privacy_class, privacy_class, "privacy_class"),
                (provision.operation, operation, "operation"),
                (provision.max_prompt_tokens, max_prompt_tokens, "max_prompt_tokens"),
                (provision.max_completion_tokens, max_completion_tokens, "max_completion_tokens"),
                (provision.endpoint.node_id, node_id, "node_id"),
            ):
                if actual != expected:
                    raise RemoteConfidentialBrokerError(f"provider confidential provision changed {label}")
            return provision
        except (PersistentControlChannelError, RemoteConfidentialBrokerError, ValueError, KeyError, TypeError) as exc:
            self._release_best_effort(decision_id)
            if isinstance(exc, RemoteConfidentialBrokerError):
                raise
            raise RemoteConfidentialBrokerError("selected confidential provider could not be provisioned") from exc


def build_remote_confidential_broker_from_env(
    *,
    registry: LiveSharedRuntimeRegistry,
) -> RemoteConfidentialSessionBroker:
    endpoint = os.environ.get("COMPUTEMESH_CONTROL_PLANE_CONFIDENTIAL_URL", "").strip()
    token = os.environ.get("COMPUTEMESH_CONTROL_PLANE_CONFIDENTIAL_TOKEN", "").strip()
    verification_key = os.environ.get("COMPUTEMESH_CONTROL_PLANE_SIGNING_PUBLIC_KEY", "").strip()
    key_id = os.environ.get("COMPUTEMESH_CONTROL_PLANE_SIGNING_KEY_ID", "").strip()
    if not endpoint:
        raise RuntimeError("COMPUTEMESH_CONTROL_PLANE_CONFIDENTIAL_URL is required")
    if not token:
        raise RuntimeError("COMPUTEMESH_CONTROL_PLANE_CONFIDENTIAL_TOKEN is required")
    if not verification_key or not key_id:
        raise RuntimeError("confidential dispatch requires the control-plane decision verification key and key id")
    ca_file = os.environ.get("COMPUTEMESH_CONTROL_PLANE_CA_FILE", "").strip() or None
    try:
        timeout = float(os.environ.get("COMPUTEMESH_CONTROL_PLANE_TIMEOUT_SECONDS", "10"))
        provider_timeout = float(os.environ.get("COMPUTEMESH_CONFIDENTIAL_PROVIDER_TIMEOUT_SECONDS", "20"))
    except ValueError as exc:
        raise RuntimeError("confidential broker timeout configuration is invalid") from exc
    return RemoteConfidentialSessionBroker(
        endpoint=endpoint,
        bearer_token=token,
        verification_key_b64u=verification_key,
        expected_key_id=key_id,
        registry=registry,
        ca_file=ca_file,
        timeout_seconds=timeout,
        provider_timeout_seconds=provider_timeout,
    )
