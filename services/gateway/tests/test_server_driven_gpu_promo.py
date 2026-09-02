from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from services.gateway.server_driven_gpu_promo import ServerDrivenGpuPromoRoutes
from services.orchestrator.authenticated_gpu_promo_transport import GpuPromoTransportResult


@dataclass
class _AuthResult:
    owner_id: str = "owner-a"
    account_id: str = "owner-a"
    error_message: str | None = None
    status_code: HTTPStatus = HTTPStatus.OK


class _Auth:
    def authenticate_request(self, headers, *, allow_teaser: bool):
        assert allow_teaser is False
        return _AuthResult()


class _OwnerStore:
    def owner_for_provider_node(self, node_id: str):
        return "owner-a" if node_id == "node-a" else None

    def promo_claim_for_owner(self, owner_id: str, claim_class: str):
        return None


@dataclass
class _Balances:
    promo_micro_units: int = 50_000_000


class _Ledger:
    def get_owner_balances(self, owner_id: str):
        return _Balances()


class _ControlPlane:
    def __init__(self) -> None:
        self.issue_body = None
        self.verify_body = None

    def issue_challenge(self, body):
        self.issue_body = body
        assert body["owner_id"] == "owner-a"
        assert body["node_id"] == "node-a"
        assert body["key_id"] == "ed25519:key-a"
        return {
            "challenge_id": "promo_ch_a",
            "claim_class": "gpu_onboarding",
            "owner_id": "owner-a",
            "node_id": "node-a",
            "key_id": "ed25519:key-a",
            "hardware_claim_id": "cmhw_v1_a",
            "evidence_digest": "sha256:" + "1" * 64,
            "nonce": "n" * 32,
            "issued_at": 1000,
            "expires_at": 1120,
            "prompt": "private selected probe",
            "seed": 7,
            "n_predict": 16,
            "model_sha256": "2" * 64,
            "expected_llama_build_number": 123,
            "expected_llama_build_commit": "abcdef1",
            "timeout_ms": 30_000,
        }

    def verify_and_issue(self, body):
        self.verify_body = body
        return {"signed": "grant"}


class _Transport:
    def __init__(self) -> None:
        self.challenge = None

    def authenticated_key_id(self, node_id):
        assert node_id == "node-a"
        return "ed25519:key-a"

    def request_gpu_promo_challenge(self, *, node_id, challenge_document, timeout_seconds):
        assert node_id == "node-a"
        assert timeout_seconds == 35.0
        self.challenge = dict(challenge_document)
        return GpuPromoTransportResult(
            proof={
                "challenge_id": "promo_ch_a",
                "claim_class": "gpu_onboarding",
                "owner_id": "owner-a",
                "node_id": "node-a",
                "key_id": "ed25519:key-a",
                "hardware_claim_id": "cmhw_v1_a",
                "evidence_digest": "sha256:" + "1" * 64,
                "nonce": "n" * 32,
                "assurance_tier": "MULTI_SIGNAL_VERIFIED",
                "public_key_b64u": "a" * 43,
                "signature_b64u": "b" * 86,
                "accelerator_id": "GPU-a",
                "runtime_backend": "cuda",
                "runtime_build": "llama.cpp:123:abcdef1;model_sha256:" + "2" * 64 + ";device:CUDA0",
                "work_digest": "sha256:" + "3" * 64,
                "elapsed_ms": 150.0,
            },
            server_roundtrip_ms=325.0,
            session_id="session-a",
            session_revision=7,
        )


@dataclass
class _Applied:
    claim_class: str = "gpu_onboarding"
    amount_micro_units: int = 25_000_000
    ledger_status: str = "applied"


class _Applier:
    def apply(self, envelope):
        assert envelope == {"signed": "grant"}
        return _Applied()


def _routes():
    cp = _ControlPlane()
    transport = _Transport()
    routes = ServerDrivenGpuPromoRoutes(
        owner_store=_OwnerStore(),  # type: ignore[arg-type]
        ledger=_Ledger(),  # type: ignore[arg-type]
        auth_manager=_Auth(),  # type: ignore[arg-type]
        control_plane=cp,  # type: ignore[arg-type]
        applier=_Applier(),  # type: ignore[arg-type]
        gpu_transport=transport,  # type: ignore[arg-type]
    )
    return routes, cp, transport


def test_gateway_obtains_gpu_proof_and_key_from_provider_session_not_request_body() -> None:
    routes, cp, transport = _routes()
    result, error, status = routes.handle_gpu_onboarding(
        {},
        {
            "node_id": "node-a",
            "hardware_evidence": {
                "platform": "linux",
                "board_uuid": "board-a",
                "gpu_ids": ["GPU-a"],
            },
        },
    )
    assert error is None
    assert status == HTTPStatus.OK
    assert result is not None and result["amount_micro_units"] == 25_000_000
    assert cp.issue_body is not None and cp.issue_body["key_id"] == "ed25519:key-a"
    assert transport.challenge is not None
    assert "work_digest" not in transport.challenge
    assert cp.verify_body is not None
    assert cp.verify_body["proof"]["work_digest"] == "sha256:" + "3" * 64
    assert cp.verify_body["server_observation"]["server_roundtrip_ms"] == 325.0


def test_client_cannot_smuggle_key_or_proof_into_server_driven_request() -> None:
    routes, _, _ = _routes()
    for extra in (
        {"proof": {"work_digest": "fake"}},
        {"key_id": "ed25519:attacker-selected"},
    ):
        body = {
            "node_id": "node-a",
            "hardware_evidence": {},
            **extra,
        }
        result, error, status = routes.handle_gpu_onboarding({}, body)
        assert result is None
        assert status == HTTPStatus.BAD_REQUEST
        assert error == "Invalid GPU promo onboarding request"


def test_foreign_provider_node_is_rejected_before_private_challenge() -> None:
    routes, cp, _ = _routes()
    result, error, status = routes.handle_gpu_onboarding(
        {},
        {
            "node_id": "node-b",
            "hardware_evidence": {},
        },
    )
    assert result is None
    assert status == HTTPStatus.FORBIDDEN
    assert "not owned" in str(error)
    assert cp.issue_body is None
    assert cp.verify_body is None
