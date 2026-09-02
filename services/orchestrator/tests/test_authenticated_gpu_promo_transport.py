from __future__ import annotations

from datetime import UTC, datetime, timedelta

from protocol.node_session import NodeSessionState, SessionSnapshot
from runtime.llama.gpu_promo_challenge import GPU_PROMO_CAPABILITY
from services.orchestrator.authenticated_gpu_promo_transport import (
    AuthenticatedGpuPromoTransportError,
    SessionAuthenticatedGpuPromoTransport,
)


class _Sessions:
    def __init__(self, session: SessionSnapshot) -> None:
        self.session = session

    def get_session(self, node_id: str) -> SessionSnapshot:
        if node_id != self.session.node_id:
            raise KeyError(node_id)
        return self.session


class _Client:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def is_connected(self, node_id: str) -> bool:
        return node_id == "node-a"

    def request(
        self,
        *,
        node_id: str,
        message_type: str,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "node_id": node_id,
                "message_type": message_type,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def _session(*, capabilities: frozenset[str] | None = None) -> SessionSnapshot:
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
        negotiated_capabilities=capabilities or frozenset({GPU_PROMO_CAPABILITY}),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


def _challenge() -> dict[str, object]:
    return {
        "schema_version": 1,
        "challenge_id": "promo_ch_abc",
        "claim_class": "gpu_onboarding",
        "owner_id": "owner-a",
        "node_id": "node-a",
        "key_id": "ed25519:key-a",
        "hardware_claim_id": "cmhw_v1_test",
        "evidence_digest": "sha256:" + "1" * 64,
        "nonce": "n" * 32,
        "prompt": "ComputeMesh GPU promo deterministic probe",
        "seed": 7,
        "n_predict": 16,
        "model_sha256": "2" * 64,
        "expected_llama_build_number": 123,
        "expected_llama_build_commit": "abcdef1",
        "timeout_ms": 30000,
    }


def _response() -> dict[str, object]:
    proof = {
        "challenge_id": "promo_ch_abc",
        "claim_class": "gpu_onboarding",
        "owner_id": "owner-a",
        "node_id": "node-a",
        "key_id": "ed25519:key-a",
        "hardware_claim_id": "cmhw_v1_test",
        "evidence_digest": "sha256:" + "1" * 64,
        "nonce": "n" * 32,
        "assurance_tier": "MULTI_SIGNAL_VERIFIED",
        "public_key_b64u": "A" * 43,
        "signature_b64u": "A" * 86,
        "accelerator_id": "GPU-uuid-a",
        "runtime_backend": "cuda",
        "runtime_build": "llama.cpp:123:abcdef1;model_sha256:" + "2" * 64 + ";device:CUDA0",
        "work_digest": "sha256:" + "3" * 64,
        "elapsed_ms": 12.5,
    }
    return {
        "session_id": "session-a",
        "session_revision": 7,
        "node_id": "node-a",
        "key_id": "ed25519:key-a",
        "proof": proof,
    }


def _assert_transport_error(fragment: str, call: object) -> None:
    try:
        call()  # type: ignore[operator]
    except AuthenticatedGpuPromoTransportError as exc:
        assert fragment in str(exc)
    else:
        raise AssertionError(
            f"expected AuthenticatedGpuPromoTransportError containing {fragment!r}"
        )


def test_gpu_promo_transport_binds_session_node_key_and_records_roundtrip() -> None:
    client = _Client(_response())
    transport = SessionAuthenticatedGpuPromoTransport(_Sessions(_session()), client)

    result = transport.request_gpu_promo_challenge(
        node_id="node-a",
        challenge_document=_challenge(),
        timeout_seconds=30.0,
    )

    assert result.proof["challenge_id"] == "promo_ch_abc"
    assert result.server_roundtrip_ms >= 0
    assert result.session_id == "session-a"
    assert result.session_revision == 7
    assert client.calls[0]["message_type"] == "GpuPromoChallengeRequest"


def test_gpu_promo_transport_fails_closed_without_negotiated_capability() -> None:
    transport = SessionAuthenticatedGpuPromoTransport(
        _Sessions(_session(capabilities=frozenset({"execution_attestation_v1"}))),
        _Client(_response()),
    )
    _assert_transport_error(
        "did not negotiate",
        lambda: transport.request_gpu_promo_challenge(
            node_id="node-a",
            challenge_document=_challenge(),
            timeout_seconds=30.0,
        ),
    )


def test_gpu_promo_transport_rejects_response_for_another_key() -> None:
    response = _response()
    proof = dict(response["proof"])
    proof["key_id"] = "ed25519:key-b"
    response["proof"] = proof
    response["key_id"] = "ed25519:key-b"
    transport = SessionAuthenticatedGpuPromoTransport(_Sessions(_session()), _Client(response))
    _assert_transport_error(
        "proof key id mismatch",
        lambda: transport.request_gpu_promo_challenge(
            node_id="node-a",
            challenge_document=_challenge(),
            timeout_seconds=30.0,
        ),
    )
