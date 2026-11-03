from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from protocol.node_session import NodeSessionState, SessionSnapshot
from services.mcp.platform.environment import (
    EnvironmentLease,
    EnvironmentOperation,
    EnvironmentRequest,
    EnvironmentSpec,
    ResourceLimits,
)
from services.orchestrator.environment_transport import (
    AuthenticatedNodeEnvironmentTransport,
    EnvironmentTransportError,
)
from services.orchestrator.model_preparation_transport import (
    AuthenticatedModelPreparationClient,
    ModelPreparationTransportError,
)


def _session(*, capabilities=("model_preparation_v1",)) -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-a",
        state=NodeSessionState.READY,
        revision=7,
        protocol_major=1,
        protocol_minor=0,
        node_id="node-a",
        principal_id="provider-a",
        auth_method="ed25519_challenge_v1",
        credential_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        negotiated_capabilities=frozenset(capabilities),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


class _ControlClient:
    def __init__(self, session: SessionSnapshot):
        self.session = session
        self.calls = []

    def session_for(self, node_id: str) -> SessionSnapshot:
        assert node_id == "node-a"
        return self.session

    def request(self, **kwargs):
        self.calls.append(kwargs)
        payload = kwargs["payload"]
        return {
            "schema_version": 1,
            "session_id": payload["session_id"],
            "session_revision": payload["session_revision"],
            "node_id": payload["node_id"],
            "model_id": payload["model_id"],
            "artifact_digest": payload["artifact_digest"],
            "status": "prepared",
        }


def _request() -> dict[str, object]:
    return {
        "operation": "prepare_model",
        "node_id": "node-a",
        "model": {
            "model_id": "qwen2.5:3b",
            "artifact_digest": "a" * 64,
            "size_bytes": 100,
            "capabilities": ("chat",),
            "context_tokens": 32768,
            "source": "verified_catalog",
        },
        "idempotency_key": "modelprep_test",
    }


def test_authenticated_model_preparation_client_binds_request_and_response() -> None:
    control = _ControlClient(_session())
    client = AuthenticatedModelPreparationClient(control)
    response = client(SimpleNamespace(node_id="node-a"), _request())
    assert response["status"] == "prepared"
    assert control.calls[0]["message_type"] == "ModelPreparationRequest"
    assert control.calls[0]["payload"]["session_id"] == "session-a"


def test_authenticated_model_preparation_requires_capability() -> None:
    control = _ControlClient(_session(capabilities=()))
    client = AuthenticatedModelPreparationClient(control)
    with pytest.raises(ModelPreparationTransportError, match="capability"):
        client(SimpleNamespace(node_id="node-a"), _request())


def test_authenticated_model_preparation_rejects_digest_mismatch() -> None:
    class BadControl(_ControlClient):
        def request(self, **kwargs):
            response = super().request(**kwargs)
            response["artifact_digest"] = "b" * 64
            return response

    client = AuthenticatedModelPreparationClient(BadControl(_session()))
    with pytest.raises(ModelPreparationTransportError, match="digest mismatch"):
        client(SimpleNamespace(node_id="node-a"), _request())


def test_authenticated_environment_transport_binds_lifecycle_and_lease() -> None:
    class Control(_ControlClient):
        def request(self, **kwargs):
            self.calls.append(kwargs)
            payload = kwargs["payload"]
            operation = payload["operation"]
            response = {
                "schema_version": 1,
                "session_id": payload["session_id"],
                "session_revision": payload["session_revision"],
                "node_id": payload["node_id"],
                "environment_id": payload["environment_id"],
                "operation": operation,
                "status": "ok",
            }
            if operation == "prepare":
                response.update({"lease_id": "lease_1", "issued_at": 100.0, "expires_at": 200.0, "lease_revision": 1})
            elif operation == "heartbeat":
                response.update({"lease_id": payload["lease_id"], "issued_at": 100.0, "expires_at": 300.0, "lease_revision": 2})
            elif operation == "execute":
                response["result"] = {"ok": True}
            return response

    control = Control(_session(capabilities=("mesh_environment_v1",)))
    transport = AuthenticatedNodeEnvironmentTransport(control, clock=lambda: 150.0)
    spec = EnvironmentSpec("env_1", "session_1", node_id="node-a", resources=ResourceLimits(max_runtime_seconds=3600))
    lease = transport.prepare(spec)
    assert transport.heartbeat(lease).revision == 2
    assert transport.execute(lease, EnvironmentRequest("req_1", EnvironmentOperation.INFERENCE, {"prompt": "hi"})) == {"ok": True}
    transport.shutdown(lease, reason="done")
    assert [call["payload"]["operation"] for call in control.calls] == ["prepare", "heartbeat", "execute", "shutdown"]


def test_authenticated_environment_transport_requires_capability_and_known_lease() -> None:
    control = _ControlClient(_session(capabilities=()))
    transport = AuthenticatedNodeEnvironmentTransport(control)
    with pytest.raises(EnvironmentTransportError, match="capability"):
        transport.prepare(EnvironmentSpec("env_1", "session_1", node_id="node-a"))
    capable = AuthenticatedNodeEnvironmentTransport(_ControlClient(_session(capabilities=("mesh_environment_v1",))))
    with pytest.raises(EnvironmentTransportError, match="unknown"):
        capable.execute(
            EnvironmentLease("missing", "env_1", 100.0, 200.0, 1),
            EnvironmentRequest("req_1", EnvironmentOperation.INFERENCE, {}),
        )
