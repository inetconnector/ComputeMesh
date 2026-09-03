import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime.confidential.protected_worker import CONFIDENTIAL_PROVISION_CAPABILITY
from services.orchestrator.remote_confidential_broker import (
    RemoteConfidentialBrokerError,
    RemoteConfidentialSessionBroker,
)


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class FakeControlClient:
    def __init__(self) -> None:
        self.requests = []
        self.fail = False

    def live_node_ids(self):
        return ("node-a", "node-b")

    def is_connected(self, node_id):
        return True

    def request(self, *, node_id, message_type, payload, timeout_seconds):
        self.requests.append((node_id, message_type, payload, timeout_seconds))
        if self.fail:
            raise ValueError("provider failed")
        request = payload["request"]
        nonce = "attested-nonce"
        runtime = "sha256:" + "1" * 64
        recipient = "recipient-public-key"
        metering = "metering-public-key"
        tls = "sha256:" + "2" * 64
        attestation = {
            "node_id": node_id,
            "runtime_digest": runtime,
            "nonce": nonce,
            "ephemeral_public_key": recipient,
            "metering_public_key": metering,
            "data_plane_tls_sha256": tls,
        }
        provision = {
            "schema_version": 1,
            "job_id": request["job_id"],
            "account_id": request["account_id"],
            "model_id": request["model_id"],
            "privacy_class": request["privacy_class"],
            "operation": request["operation"],
            "max_prompt_tokens": request["max_prompt_tokens"],
            "max_completion_tokens": request["max_completion_tokens"],
            "expires_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat().replace("+00:00", "Z"),
            "endpoint": {
                "url": "https://node-a.example/protected",
                "node_id": node_id,
                "runtime_digest": runtime,
                "attestation_nonce": nonce,
                "recipient_public_key": recipient,
                "metering_public_key": metering,
                "tls_certificate_sha256": tls,
            },
            "attestation": attestation,
        }
        return {
            "session_id": payload["session_id"],
            "session_revision": payload["session_revision"],
            "node_id": node_id,
            "provision": provision,
        }


class FakeRegistry:
    def __init__(self) -> None:
        self.control_client = FakeControlClient()
        self.sessions = {
            "node-a": SimpleNamespace(
                session_id="session-a",
                revision=7,
                negotiated_capabilities=frozenset({CONFIDENTIAL_PROVISION_CAPABILITY}),
            ),
            "node-b": SimpleNamespace(
                session_id="session-b",
                revision=9,
                negotiated_capabilities=frozenset(),
            ),
        }

    def get_session(self, node_id):
        return self.sessions[node_id]

    def is_node_control_healthy(self, node_id):
        return self.control_client.is_connected(node_id)


class BrokerUnderTest(RemoteConfidentialSessionBroker):
    def __init__(self, *, signing_key, **kwargs):
        super().__init__(**kwargs)
        self.signing_key = signing_key
        self.private_requests = []
        self.releases = []
        self.select_unsubmitted = False

    def _post(self, endpoint, body):
        self.private_requests.append((endpoint, body))
        if endpoint == self.release_endpoint:
            self.releases.append(body["decision_id"])
            return {"schema_version": 1, "released": True}
        candidate = body["candidates"][0]
        node_id = "node-evil" if self.select_unsubmitted else candidate["node_id"]
        now = datetime.now(UTC)
        envelope = {
            "schema_version": 1,
            "decision_type": "confidential_dispatch",
            "decision_id": "decision-a",
            "issued_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
            "payload": {
                "admission_id": body["admission_id"],
                "job_id": "job-a",
                "account_id": body["account_id"],
                "model_id": body["model_id"],
                "privacy_class": body["privacy_class"],
                "operation": body["operation"],
                "max_prompt_tokens": body["max_prompt_tokens"],
                "max_completion_tokens": body["max_completion_tokens"],
                "node_id": node_id,
                "session_id": candidate["session_id"],
                "session_revision": candidate["session_revision"],
                "freshness_challenge": "fresh-challenge",
            },
        }
        canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        envelope["signature"] = {
            "algorithm": "Ed25519",
            "key_id": "decision-key",
            "value": _b64u(self.signing_key.sign(canonical)),
        }
        return envelope


def _broker():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    registry = FakeRegistry()
    broker = BrokerUnderTest(
        signing_key=key,
        endpoint="https://control.example/internal/v1/confidential/dispatch",
        bearer_token="confidential-token",
        verification_key_b64u=_b64u(public),
        expected_key_id="decision-key",
        registry=registry,
    )
    return broker, registry


def test_broker_submits_only_live_confidential_sessions_and_dispatches_selected_node():
    broker, registry = _broker()
    provision = broker.provision(
        account_id="owner-a",
        model_id="model-a",
        privacy_class="CONFIDENTIAL",
        operation="chat_completion",
        max_prompt_tokens=2048,
        max_completion_tokens=512,
    )
    _, private_body = broker.private_requests[0]
    assert private_body["candidates"] == [
        {"node_id": "node-a", "session_id": "session-a", "session_revision": 7}
    ]
    assert "prompt" not in repr(private_body).lower()
    node_id, message_type, provider_body, _ = registry.control_client.requests[0]
    assert node_id == "node-a"
    assert message_type == "ConfidentialSessionProvisionRequest"
    assert provider_body["freshness_challenge"] == "fresh-challenge"
    assert provider_body["request"]["job_id"] == "job-a"
    assert provision.job_id == "job-a"
    assert provision.endpoint.node_id == "node-a"


def test_broker_rejects_private_selection_of_unsubmitted_node():
    broker, _ = _broker()
    broker.select_unsubmitted = True
    with pytest.raises(RemoteConfidentialBrokerError, match="unsubmitted"):
        broker.provision(
            account_id="owner-a",
            model_id="model-a",
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=128,
            max_completion_tokens=64,
        )


def test_provider_failure_releases_private_lease_best_effort():
    broker, registry = _broker()
    registry.control_client.fail = True
    with pytest.raises(RemoteConfidentialBrokerError, match="could not be provisioned"):
        broker.provision(
            account_id="owner-a",
            model_id="model-a",
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=128,
            max_completion_tokens=64,
        )
    assert broker.releases == ["decision-a"]


def test_crypto_private_remains_fail_closed():
    broker, _ = _broker()
    with pytest.raises(RemoteConfidentialBrokerError, match="CONFIDENTIAL only"):
        broker.provision(
            account_id="owner-a",
            model_id="model-a",
            privacy_class="CRYPTO_PRIVATE",
            operation="chat_completion",
            max_prompt_tokens=128,
            max_completion_tokens=64,
        )
