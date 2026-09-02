from __future__ import annotations

import threading
import unittest

from services.gateway.gpu_promo_dispatch_client import (
    GpuPromoDispatchClient,
    GpuPromoDispatchClientError,
)
from services.orchestrator.authenticated_gpu_promo_transport import (
    AuthenticatedGpuPromoTransportError,
    GpuPromoTransportResult,
)
from services.orchestrator.gpu_promo_dispatch import create_gpu_promo_dispatch_server


class _Transport:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.identity_calls: list[str] = []
        self.available = True

    def authenticated_key_id(self, node_id: str) -> str:
        self.identity_calls.append(node_id)
        if not self.available:
            raise AuthenticatedGpuPromoTransportError("no live session")
        return "ed25519:key-a"

    def request_gpu_promo_challenge(
        self,
        *,
        node_id: str,
        challenge_document: dict,
        timeout_seconds: float,
    ) -> GpuPromoTransportResult:
        self.calls.append(
            {
                "node_id": node_id,
                "challenge": challenge_document,
                "timeout_seconds": timeout_seconds,
            }
        )
        return GpuPromoTransportResult(
            proof={
                "challenge_id": challenge_document["challenge_id"],
                "claim_class": "gpu_onboarding",
                "owner_id": "alice",
                "node_id": node_id,
                "key_id": "ed25519:key-a",
            },
            server_roundtrip_ms=321.5,
            session_id="session-a",
            session_revision=7,
        )


class TestGpuPromoDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = _Transport()
        self.server = create_gpu_promo_dispatch_server(
            transport=self.transport,  # type: ignore[arg-type]
            bearer_token="gpu-dispatch-test-token-123456",
            port=0,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = GpuPromoDispatchClient(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            bearer_token="gpu-dispatch-test-token-123456",
            timeout_seconds=5.0,
        )
        self.challenge = {
            "schema_version": 1,
            "challenge_id": "promo_ch_abc",
            "claim_class": "gpu_onboarding",
            "owner_id": "alice",
            "node_id": "node-a",
            "key_id": "ed25519:key-a",
            "hardware_claim_id": "cmhw_v1_test",
            "evidence_digest": "sha256:" + "1" * 64,
            "nonce": "n" * 32,
            "prompt": "ComputeMesh deterministic GPU promo probe",
            "seed": 7,
            "n_predict": 16,
            "model_sha256": "2" * 64,
            "expected_llama_build_number": 123,
            "expected_llama_build_commit": "abcdef1",
            "timeout_ms": 30_000,
        }

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_real_http_session_identity_returns_authenticated_key_only(self) -> None:
        key_id = self.client.authenticated_key_id(node_id="node-a")
        self.assertEqual(key_id, "ed25519:key-a")
        self.assertEqual(self.transport.identity_calls, ["node-a"])
        self.assertEqual(self.transport.calls, [])

    def test_real_http_dispatch_returns_only_proof_and_server_observation(self) -> None:
        result = self.client.dispatch(node_id="node-a", challenge=self.challenge)
        self.assertEqual(set(result), {"proof", "gpu_observation"})
        self.assertEqual(result["proof"]["challenge_id"], "promo_ch_abc")
        self.assertEqual(result["gpu_observation"]["server_roundtrip_ms"], 321.5)
        self.assertEqual(result["gpu_observation"]["session_id"], "session-a")
        self.assertEqual(self.transport.calls[0]["node_id"], "node-a")
        self.assertEqual(self.transport.calls[0]["challenge"], self.challenge)

    def test_missing_live_session_fails_closed_for_identity_lookup(self) -> None:
        self.transport.available = False
        with self.assertRaises(GpuPromoDispatchClientError) as caught:
            self.client.authenticated_key_id(node_id="node-a")
        self.assertEqual(caught.exception.status_code, 503)

    def test_wrong_dispatch_token_fails_closed(self) -> None:
        client = GpuPromoDispatchClient(
            base_url=f"http://127.0.0.1:{self.server.server_address[1]}",
            bearer_token="wrong-but-long-enough-token-1234",
            timeout_seconds=5.0,
        )
        with self.assertRaises(GpuPromoDispatchClientError) as caught:
            client.authenticated_key_id(node_id="node-a")
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(self.transport.identity_calls, [])
        self.assertEqual(self.transport.calls, [])

    def test_dispatch_client_rejects_non_loopback_plaintext(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            GpuPromoDispatchClient(
                base_url="http://192.168.1.20:7490",
                bearer_token="gpu-dispatch-test-token-123456",
            )


if __name__ == "__main__":
    unittest.main()
