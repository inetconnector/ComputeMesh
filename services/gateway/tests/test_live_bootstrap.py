import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.gateway.inference_backend import InferenceBackendError
from services.gateway.live_bootstrap import build_live_shared_backend_from_env
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry
from services.orchestrator.placement_provider import ReferencePlacementProvider, RemotePlacementProvider
from services.orchestrator.private_feedback import PrivateOutcomeFeedback


def _public_key_b64u() -> str:
    public = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")


class LiveBootstrapTests(unittest.TestCase):
    def _base_env(self, root: Path) -> dict[str, str]:
        return {
            "COMPUTEMESH_ORCHESTRATOR_STATE_PATH": str(root / "orch.sqlite3"),
            "COMPUTEMESH_IDENTITY_STATE_PATH": str(root / "identity.sqlite3"),
            "COMPUTEMESH_LLAMA_SERVER_PATH": str(root / "llama-server"),
            "COMPUTEMESH_SHARED_WORK_ROOT": str(root / "work"),
        }

    def _remote_env(self, root: Path) -> dict[str, str]:
        return {
            "COMPUTEMESH_PLACEMENT_MODE": "remote",
            "COMPUTEMESH_CONTROL_PLANE_PLACEMENT_URL": "https://control.example.test/v1/placement",
            "COMPUTEMESH_CONTROL_PLANE_TOKEN": "test-token",
            "COMPUTEMESH_CONTROL_PLANE_SIGNING_PUBLIC_KEY": _public_key_b64u(),
            "COMPUTEMESH_CONTROL_PLANE_SIGNING_KEY_ID": "placement-signing-v1",
            "COMPUTEMESH_CONTROL_PLANE_OUTCOME_URL": "https://control.example.test/internal/v1/outcomes",
            "COMPUTEMESH_CONTROL_PLANE_INTERNAL_TOKEN": "internal-test-token",
            "COMPUTEMESH_PRIVATE_FEEDBACK_OUTBOX_PATH": str(root / "feedback.sqlite3"),
        }

    def test_defaults_to_remote_and_fails_closed_without_control_plane_config(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, self._base_env(root), clear=True):
                with self.assertRaises(InferenceBackendError):
                    build_live_shared_backend_from_env(registry=LiveSharedRuntimeRegistry())

    def test_reference_mode_requires_explicit_experimental_opt_in(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            env = self._base_env(root) | {"COMPUTEMESH_PLACEMENT_MODE": "reference"}
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(InferenceBackendError):
                    build_live_shared_backend_from_env(registry=LiveSharedRuntimeRegistry())

    def test_remote_mode_requires_private_feedback_outbox_and_internal_endpoint(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            env = self._base_env(root) | {
                "COMPUTEMESH_PLACEMENT_MODE": "remote",
                "COMPUTEMESH_CONTROL_PLANE_PLACEMENT_URL": "https://control.example.test/v1/placement",
                "COMPUTEMESH_CONTROL_PLANE_TOKEN": "test-token",
                "COMPUTEMESH_CONTROL_PLANE_SIGNING_PUBLIC_KEY": _public_key_b64u(),
                "COMPUTEMESH_CONTROL_PLANE_SIGNING_KEY_ID": "placement-signing-v1",
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(InferenceBackendError):
                    build_live_shared_backend_from_env(registry=LiveSharedRuntimeRegistry())

    def test_remote_mode_installs_private_provider_and_durable_feedback(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            registry = LiveSharedRuntimeRegistry()
            env = self._base_env(root) | self._remote_env(root)
            with patch.dict(os.environ, env, clear=True):
                backend = build_live_shared_backend_from_env(registry=registry)
            self.assertFalse(backend.allow_experimental)
            self.assertIsInstance(registry._placement_provider, RemotePlacementProvider)
            self.assertIsInstance(backend.outcome_feedback, PrivateOutcomeFeedback)
            self.assertTrue((root / "feedback.sqlite3").is_file())

    def test_refuses_prepositioned_settlement_artifacts(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            env = self._base_env(root) | {
                "COMPUTEMESH_PLACEMENT_MODE": "reference",
                "COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT": "1",
                "COMPUTEMESH_ORCHESTRATOR_PLACEMENT_DECISION": str(root / "placement.json"),
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(InferenceBackendError):
                    build_live_shared_backend_from_env(registry=LiveSharedRuntimeRegistry())

    def test_reference_mode_builds_only_with_explicit_opt_in(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            registry = LiveSharedRuntimeRegistry()
            env = self._base_env(root) | {
                "COMPUTEMESH_PLACEMENT_MODE": "reference",
                "COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT": "1",
            }
            with patch.dict(os.environ, env, clear=True):
                backend = build_live_shared_backend_from_env(registry=registry)
            self.assertEqual(backend.work_root, root / "work")
            self.assertTrue(backend.allow_experimental)
            self.assertIsNone(backend.outcome_feedback)
            self.assertIsInstance(registry._placement_provider, ReferencePlacementProvider)


if __name__ == "__main__":
    unittest.main()
