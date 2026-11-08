import hashlib
import json
import tempfile
import threading
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from services.appliance_dashboard.model_manager import (
    MODEL_SAFETY_RESERVE_BYTES,
    ModelManager,
    ModelManagerError,
)


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
            with patch("services.appliance_dashboard.model_manager.urllib.request.urlopen", return_value=FakeResponse(body)), self.assertRaisesRegex(ModelManagerError, "SHA-256"):
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

    def test_status_warns_when_storage_cannot_fit_recommended_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(Path(tmp), engine=FakeEngine())
            usage = type("Usage", (), {"total": 10 * 1024**3, "used": 9 * 1024**3, "free": 1 * 1024**3})()
            with patch("services.appliance_dashboard.model_manager.shutil.disk_usage", return_value=usage):
                storage = manager.status()["storage"]
            self.assertTrue(storage["warning"])
            self.assertFalse(storage["sufficient_for_recommended_model"])
            self.assertEqual(storage["safety_reserve_bytes"], MODEL_SAFETY_RESERVE_BYTES)

    def test_download_error_reports_available_and_required_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(Path(tmp), engine=FakeEngine())
            usage = type("Usage", (), {"total": 10 * 1024**3, "used": 9 * 1024**3, "free": 2 * 1024**3})()
            with patch("services.appliance_dashboard.model_manager.shutil.disk_usage", return_value=usage), self.assertRaisesRegex(ModelManagerError, "available.*required"):
                manager.install_from_hugging_face(
                    model_id="org/model-q4",
                    repo_id="org/model-gguf",
                    filename="model-q4.gguf",
                    revision="a" * 40,
                    sha256="0" * 64,
                    size_bytes=2 * 1024**3,
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

    def test_discover_and_register_local_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gguf_path = root / "qwen2.5-32b-instruct.gguf"
            # 1.5 MB dummy GGUF
            content = b"GGUF" + b"\x00" * (1024 * 1024 + 100)
            gguf_path.write_bytes(content)

            manifest_path = root / "qwen2.5-32b-instruct.computemesh-model-manifest.json"
            manifest = {
                "model_id": "qwen2.5-32b-instruct",
                "layer_count": 64,
                "quantizations": ["Q4_K_M"],
                "artifacts": [{"digest": f"sha256:{hashlib.sha256(content).hexdigest()}"}],
                "license": {"id": "apache-2.0"},
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            manager = ModelManager(root, engine=FakeEngine())
            discovered = manager.discover_and_register_local_artifacts()
            self.assertEqual(discovered, ["qwen2.5-32b-instruct"])

            models = manager.list_models()
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]["model_id"], "qwen2.5-32b-instruct")
            self.assertEqual(models[0]["layer_count"], 64)
            self.assertEqual(models[0]["quantization"], "Q4_K_M")

    def test_ensure_best_model_for_rig_tiering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = FakeEngine()
            manager = ModelManager(root, engine=engine)

            # Install a 32b and a 7b model
            body_32b = b"GGUF" + b"\x01" * 1024
            body_7b = b"GGUF" + b"\x02" * 1024
            (root / "model-32b.gguf").write_bytes(body_32b)
            (root / "model-7b.gguf").write_bytes(body_7b)

            models_data = {
                "schema_version": 1,
                "models": [
                    {
                        "model_id": "qwen2.5-32b",
                        "filename": "model-32b.gguf",
                        "sha256": hashlib.sha256(body_32b).hexdigest(),
                        "size_bytes": len(body_32b),
                        "layer_count": 64,
                        "quantization": "Q4_K_M",
                        "license_id": "apache-2.0",
                        "source_repo": "local/qwen2.5-32b",
                        "source_revision": "0" * 40,
                        "installed_at": "2026-11-08T00:00:00Z",
                    },
                    {
                        "model_id": "qwen2.5-7b",
                        "filename": "model-7b.gguf",
                        "sha256": hashlib.sha256(body_7b).hexdigest(),
                        "size_bytes": len(body_7b),
                        "layer_count": 32,
                        "quantization": "Q4_K_M",
                        "license_id": "apache-2.0",
                        "source_repo": "local/qwen2.5-7b",
                        "source_revision": "0" * 40,
                        "installed_at": "2026-11-08T00:00:00Z",
                    },
                ],
            }
            (root / "catalog.json").write_text(json.dumps(models_data), encoding="utf-8")

            # 1. 48 GB Rig (6x 8GB GPUs) -> Should pick 32b model
            inventory_48gb = {
                "gpus": [
                    {"vendor": "amd", "model_name": "Radeon RX 470", "vram_bytes": 8 * 1024**3, "healthy": True}
                    for _ in range(6)
                ]
            }
            res_48 = manager.ensure_best_model_for_rig(inventory_48gb)
            self.assertIsNotNone(res_48)
            self.assertEqual(res_48["model_id"], "qwen2.5-32b")
            self.assertEqual(engine.current, "qwen2.5-32b")

            # 2. 16 GB PC (1x RTX 3080) -> Should pick 7b model
            inventory_16gb = {
                "gpus": [
                    {"vendor": "nvidia", "model_name": "GeForce RTX 3080", "vram_bytes": 16 * 1024**3, "healthy": True}
                ]
            }
            res_16 = manager.ensure_best_model_for_rig(inventory_16gb)
            self.assertIsNotNone(res_16)
            self.assertEqual(res_16["model_id"], "qwen2.5-7b")
            self.assertEqual(engine.current, "qwen2.5-7b")


if __name__ == "__main__":
    unittest.main()
