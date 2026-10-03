from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from services.appliance_dashboard.model_manager import ModelManager, ModelManagerError


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200):
        self._body = BytesIO(body)
        self.headers = FakeHeaders({"Content-Length": str(len(body))})
        self.status = status

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status


class FakeEngine:
    def __init__(self):
        self.current = ""

    def status(self):
        return {"state": "ready" if self.current else "stopped", "ready": bool(self.current), "model_id": self.current}

    def start(self, model, context_size=4096):
        self.current = model.model_id
        return self.status()

    def stop(self):
        self.current = ""
        return self.status()


class TestModelManager(unittest.TestCase):
    def _install(self, manager: ModelManager, body: bytes):
        digest = hashlib.sha256(body).hexdigest()
        with patch("services.appliance_dashboard.model_manager.urllib.request.urlopen", return_value=FakeResponse(body)):
            return manager.install_from_hugging_face(
                model_id="org/model-q4",
                repo_id="org/model-gguf",
                filename="model-q4.gguf",
                revision="a" * 40,
                sha256=digest,
                size_bytes=len(body),
                layer_count=32,
                quantization="Q4_K_M",
                license_id="apache-2.0",
            )

    def test_verified_download_activate_stop_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = FakeEngine()
            manager = ModelManager(Path(tmp), engine=engine)
            result = self._install(manager, b"GGUF" + b"payload")
            self.assertEqual(result["model_id"], "org/model-q4")
            self.assertEqual(len(manager.list_models()), 1)
            self.assertTrue(manager.activate("org/model-q4")["ready"])
            with self.assertRaisesRegex(ModelManagerError, "stopped"):
                manager.delete("org/model-q4")
            manager.deactivate("org/model-q4")
            self.assertTrue(manager.delete("org/model-q4")["deleted"])

    def test_digest_mismatch_leaves_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(Path(tmp), engine=FakeEngine())
            body = b"GGUF" + b"payload"
            with patch("services.appliance_dashboard.model_manager.urllib.request.urlopen", return_value=FakeResponse(body)):
                with self.assertRaisesRegex(ModelManagerError, "SHA-256"):
                    manager.install_from_hugging_face(
                        model_id="org/model-q4",
                        repo_id="org/model-gguf",
                        filename="model-q4.gguf",
                        revision="a" * 40,
                        sha256="0" * 64,
                        size_bytes=len(body),
                        layer_count=32,
                        quantization="Q4_K_M",
                        license_id="apache-2.0",
                    )
            self.assertFalse((Path(tmp) / "model-q4.gguf").exists())
            self.assertFalse((Path(tmp) / "model-q4.gguf.part").exists())

    def test_requires_pinned_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(Path(tmp), engine=FakeEngine())
            with self.assertRaisesRegex(ModelManagerError, "40-character"):
                manager.install_from_hugging_face(
                    model_id="org/model-q4",
                    repo_id="org/model-gguf",
                    filename="model-q4.gguf",
                    revision="main",
                    sha256="0" * 64,
                    size_bytes=12,
                    layer_count=32,
                    quantization="Q4_K_M",
                    license_id="apache-2.0",
                )

    def test_partial_download_resumes_with_range_and_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = ModelManager(root, engine=FakeEngine())
            body = b"GGUF" + b"resumable-payload"
            first = body[:8]
            (root / "model-q4.gguf.part").write_bytes(first)
            seen_range = []

            def open_resume(request, timeout=0):
                seen_range.append(request.headers.get("Range"))
                return FakeResponse(body[len(first):], status=206)

            with patch("services.appliance_dashboard.model_manager.urllib.request.urlopen", side_effect=open_resume):
                result = manager.install_from_hugging_face(
                    model_id="org/model-q4",
                    repo_id="org/model-gguf",
                    filename="model-q4.gguf",
                    revision="a" * 40,
                    sha256=hashlib.sha256(body).hexdigest(),
                    size_bytes=len(body),
                    layer_count=32,
                    quantization="Q4_K_M",
                    license_id="apache-2.0",
                )
            self.assertEqual(seen_range, [f"bytes={len(first)}-"])
            self.assertEqual(result["model_id"], "org/model-q4")
            self.assertEqual((root / "model-q4.gguf").read_bytes(), body)

    def test_start_download_returns_before_worker_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(Path(tmp), engine=FakeEngine())
            started = threading.Event()
            release = threading.Event()

            def blocked_install(**kwargs):
                started.set()
                release.wait(2)
                return {}

            with patch.object(manager, "install_from_hugging_face", side_effect=blocked_install):
                result = manager.start_download(
                    model_id="org/model-q4",
                    repo_id="org/model-gguf",
                    filename="model-q4.gguf",
                    revision="a" * 40,
                    sha256="0" * 64,
                    size_bytes=12,
                    layer_count=32,
                    quantization="Q4_K_M",
                    license_id="apache-2.0",
                )
                self.assertTrue(result["accepted"])
                self.assertTrue(started.wait(1))
                self.assertFalse(release.is_set())
                release.set()
                time.sleep(0.01)

    def test_corrupt_catalog_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog.json").write_text(json.dumps({"models": []}), encoding="utf-8")
            manager = ModelManager(root, engine=FakeEngine())
            with self.assertRaisesRegex(ModelManagerError, "corrupt"):
                manager.list_models()


if __name__ == "__main__":
    unittest.main()
