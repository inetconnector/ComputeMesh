"""Minimal HTTPS client for private confidential-session provision.

Only content-free admission metadata crosses this boundary. Candidate pools,
ranking scores, pricing coefficients and fraud/reputation features stay private.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
from typing import Any, Mapping
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from runtime.confidential.data_plane import AttestedConfidentialEndpoint
from runtime.confidential.session import ConfidentialSessionError, ConfidentialSessionProvision


MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_PATH = "/internal/v1/confidential/session-provision"


class RemoteConfidentialBrokerError(ConfidentialSessionError):
    pass


class RemoteConfidentialSessionBroker:
    """Trusted control-plane client implementing the public broker protocol."""

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str,
        ca_file: Path | str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = urlparse.urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("confidential control-plane endpoint must use HTTPS")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("confidential control-plane endpoint must not embed credentials")
        if not parsed.path or parsed.path == "/":
            parsed = parsed._replace(path=DEFAULT_PATH)
            endpoint = urlparse.urlunparse(parsed)
        if not bearer_token or len(bearer_token) > 4096:
            raise ValueError("confidential control-plane bearer token is invalid")
        if not 0.5 <= float(timeout_seconds) <= 120.0:
            raise ValueError("confidential control-plane timeout must be between 0.5 and 120 seconds")
        self.endpoint = endpoint
        self.bearer_token = bearer_token
        self.timeout_seconds = float(timeout_seconds)
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
        body = {
            "schema_version": 1,
            "account_id": account_id,
            "model_id": model_id,
            "privacy_class": privacy_class,
            "operation": operation,
            "max_prompt_tokens": max_prompt_tokens,
            "max_completion_tokens": max_completion_tokens,
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urlrequest.Request(
            self.endpoint,
            data=raw,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Content-Length": str(len(raw)),
                "User-Agent": "ComputeMesh-Gateway/ProtectedBroker-1",
            },
        )
        try:
            with urlrequest.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                response_raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(response.status)
        except urlerror.HTTPError as exc:
            raise RemoteConfidentialBrokerError(
                f"confidential control plane rejected admission with HTTP {exc.code}"
            ) from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise RemoteConfidentialBrokerError("confidential control plane is unavailable") from exc
        if status != 200 or len(response_raw) > MAX_RESPONSE_BYTES:
            raise RemoteConfidentialBrokerError("invalid confidential control-plane response")
        try:
            value = json.loads(response_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteConfidentialBrokerError("malformed confidential control-plane response") from exc
        if not isinstance(value, Mapping):
            raise RemoteConfidentialBrokerError("invalid confidential control-plane response")
        return self._parse_provision(value)


def build_remote_confidential_broker_from_env() -> RemoteConfidentialSessionBroker:
    endpoint = os.environ.get("COMPUTEMESH_CONTROL_PLANE_CONFIDENTIAL_URL", "").strip()
    token = os.environ.get("COMPUTEMESH_CONTROL_PLANE_INTERNAL_TOKEN", "").strip()
    if not endpoint:
        raise RuntimeError("COMPUTEMESH_CONTROL_PLANE_CONFIDENTIAL_URL is required")
    if not token:
        raise RuntimeError("COMPUTEMESH_CONTROL_PLANE_INTERNAL_TOKEN is required")
    ca_file = os.environ.get("COMPUTEMESH_CONTROL_PLANE_CA_FILE", "").strip() or None
    try:
        timeout = float(os.environ.get("COMPUTEMESH_CONTROL_PLANE_TIMEOUT_SECONDS", "10"))
    except ValueError as exc:
        raise RuntimeError("COMPUTEMESH_CONTROL_PLANE_TIMEOUT_SECONDS is invalid") from exc
    return RemoteConfidentialSessionBroker(
        endpoint=endpoint,
        bearer_token=token,
        ca_file=ca_file,
        timeout_seconds=timeout,
    )
