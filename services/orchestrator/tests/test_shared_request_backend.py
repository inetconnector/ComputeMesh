from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.node_identity import VerificationKey, key_id_from_public_key
from runtime.llama.shared_request import SharedRequestResult, build_shared_request_evidence
from services.gateway.execution_attestation import AttestationClaims, create_execution_attestation
from services.gateway.placement_selection import PlacementSelection
from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.shared_request_backend import SharedRequestOrchestratedBackend
from services.orchestrator.state_machine import JobState, ReservationState
from runtime.llama.rpc_spike import RpcEndpoint


MODEL_SHA = "a" * 64


class _Plan:
    placement_decision_id = "placement-0123456789abcdef"
    model_basename = "model.gguf"
    model_size_bytes = 1234
    model_sha256 = MODEL_SHA
    tensor_split = (8.0, 24.0)
    layer_ranges = (
        {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 8},
        {"node_id": "node-b", "start_layer": 8, "end_layer_exclusive": 32},
    )
    coordinator_node_id = "node-a"
    worker_node_id = "node-b"


class _Resolver:
    def __init__(self, records):
        self.records = records

    def resolve_key(self, node_id, key_id):
        record = self.records.get((node_id, key_id))
        if record is None:
            raise KeyError((node_id, key_id))
        return record


class _SigningTransport:
    def __init__(self, keys):
        self.keys = keys

    def request_execution_attestation(self, *, node_id, request_document, timeout_seconds):
        key = self.keys[node_id]
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        key_id = key_id_from_public_key(public)
        now = datetime.now(timezone.utc)
        claims = AttestationClaims(
            node_id=node_id,
            key_id=key_id,
            job_id=request_document["job_id"],
            placement_decision_id=request_document["placement_decision_id"],
            model_sha256=request_document["model_sha256"],
            runtime_sha256=request_document["runtime_sha256"],
            evidence_sha256=request_document["evidence_sha256"],
            output_sha256=request_document["output_sha256"],
            issued_at=int(now.timestamp()),
            expires_at=int((now + timedelta(minutes=2)).timestamp()),
        )
        return create_execution_attestation(private_key=key, claims=claims)


class SharedRequestBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SQLiteStateStore(self.root / "state.sqlite3")
        self.backends = []
        self.placement = PlacementSelection(
            decision_id="placement-0123456789abcdef",
            model_id="test-model",
            artifact_digest="sha256:" + MODEL_SHA,
            provider_node_ids=("node-a", "node-b"),
            layer_ranges=(("node-a", 0, 8), ("node-b", 8, 32)),
        )
        self.keys = {"node-a": Ed25519PrivateKey.generate(), "node-b": Ed25519PrivateKey.generate()}
        records = {}
        for node, key in self.keys.items():
            public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            kid = key_id_from_public_key(public)
            records[(node, kid)] = VerificationKey(node, f"provider:{node}", kid, public)
        self.resolver = _Resolver(records)

    def tearDown(self):
        for backend in reversed(self.backends):
            backend.close()
        self.store.close()
        self.tmp.cleanup()

    def _runner(self, **kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=False)
        text = "real shared output"
        evidence = build_shared_request_evidence(
            job_id=kwargs["job_id"],
            plan=_Plan(),
            runtime_version_text="llama.cpp build 123 abcdef0",
            prompt=kwargs["prompt"],
            content=text,
            timings={"prompt_n": 12, "predicted_n": 6, "request_ms": 50.0},
            relay_metrics={"client_to_target_bytes": 100, "target_to_client_bytes": 200},
        )
        path = output_dir / "shared_request_evidence.json"
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return SharedRequestResult(text, 12, 6, path)

    def test_end_to_end_signed_shared_request_returns_evidence_derived_shares(self):
        backend = SharedRequestOrchestratedBackend(
            store=self.store,
            placement=self.placement,
            bundle_path=self.root / "unused-bundle.json",
            llama_server=self.root / "unused-llama-server",
            model_path=self.root / "unused-model.gguf",
            worker_rpc=RpcEndpoint("127.0.0.1", 50052),
            work_root=self.root / "jobs",
            attestation_transport=_SigningTransport(self.keys),
            attestation_resolver=self.resolver,
            id_factory=lambda: "job-shared-1",
            runner=self._runner,
        )
        self.backends.append(backend)
        result = backend.complete(model_id="test-model", messages=[{"role": "user", "content": "hello"}])
        self.assertEqual(result.text, "real shared output")
        self.assertEqual(result.execution_job_id, "job-shared-1")
        self.assertEqual(result.provider_shares, (("node-a", 0.25), ("node-b", 0.75)))
        self.assertTrue(result.evidence_id.startswith("shared-request-evidence-"))
        self.assertEqual(self.store.get_job("job-shared-1").state, JobState.COMPLETED)
        for reservation_id in backend._reservation_ids("job-shared-1"):
            self.assertEqual(self.store.get_reservation(reservation_id).state, ReservationState.RELEASED)

    def test_missing_node_signature_fails_job_and_never_completes(self):
        class BrokenTransport(_SigningTransport):
            def request_execution_attestation(self, *, node_id, request_document, timeout_seconds):
                if node_id == "node-b":
                    raise RuntimeError("node lost")
                return super().request_execution_attestation(node_id=node_id, request_document=request_document, timeout_seconds=timeout_seconds)

        backend = SharedRequestOrchestratedBackend(
            store=self.store,
            placement=self.placement,
            bundle_path=self.root / "unused-bundle.json",
            llama_server=self.root / "unused-llama-server",
            model_path=self.root / "unused-model.gguf",
            worker_rpc=RpcEndpoint("127.0.0.1", 50052),
            work_root=self.root / "jobs",
            attestation_transport=BrokenTransport(self.keys),
            attestation_resolver=self.resolver,
            id_factory=lambda: "job-shared-fail",
            runner=self._runner,
        )
        self.backends.append(backend)
        with self.assertRaisesRegex(Exception, "shared-request orchestration failed"):
            backend.complete(model_id="test-model", messages=[{"role": "user", "content": "hello"}])
        self.assertEqual(self.store.get_job("job-shared-fail").state, JobState.FAILED)


if __name__ == "__main__":
    unittest.main()
