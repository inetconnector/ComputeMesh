import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.gateway.inference_backend import InferenceBackendError
from services.gateway.live_bootstrap import build_live_shared_backend_from_env
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry


class LiveBootstrapTests(unittest.TestCase):
    def test_requires_explicit_experimental_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "COMPUTEMESH_ORCHESTRATOR_STATE_PATH": str(root / "orch.sqlite3"),
                "COMPUTEMESH_IDENTITY_STATE_PATH": str(root / "identity.sqlite3"),
                "COMPUTEMESH_LLAMA_SERVER_PATH": str(root / "llama-server"),
                "COMPUTEMESH_SHARED_WORK_ROOT": str(root / "work"),
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(InferenceBackendError):
                    build_live_shared_backend_from_env(registry=LiveSharedRuntimeRegistry())

    def test_refuses_prepositioned_settlement_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "COMPUTEMESH_ORCHESTRATOR_STATE_PATH": str(root / "orch.sqlite3"),
                "COMPUTEMESH_IDENTITY_STATE_PATH": str(root / "identity.sqlite3"),
                "COMPUTEMESH_LLAMA_SERVER_PATH": str(root / "llama-server"),
                "COMPUTEMESH_SHARED_WORK_ROOT": str(root / "work"),
                "COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT": "1",
                "COMPUTEMESH_ORCHESTRATOR_PLACEMENT_DECISION": str(root / "placement.json"),
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(InferenceBackendError):
                    build_live_shared_backend_from_env(registry=LiveSharedRuntimeRegistry())

    def test_builds_without_placement_evidence_or_attestation_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "COMPUTEMESH_ORCHESTRATOR_STATE_PATH": str(root / "orch.sqlite3"),
                "COMPUTEMESH_IDENTITY_STATE_PATH": str(root / "identity.sqlite3"),
                "COMPUTEMESH_LLAMA_SERVER_PATH": str(root / "llama-server"),
                "COMPUTEMESH_SHARED_WORK_ROOT": str(root / "work"),
                "COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT": "1",
            }
            with patch.dict(os.environ, env, clear=True):
                backend = build_live_shared_backend_from_env(registry=LiveSharedRuntimeRegistry())
            self.assertEqual(backend.work_root, root / "work")
            self.assertTrue(backend.allow_experimental)


if __name__ == "__main__":
    unittest.main()
