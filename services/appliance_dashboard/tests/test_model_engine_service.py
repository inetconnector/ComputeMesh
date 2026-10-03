from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from services.appliance_dashboard.model_engine_service import EngineModel, ModelEngineError, ModelEngineService
from tools.appliance.hardware_detector import GpuDevice, RigInventory


class FakeProcess:
    def __init__(self, command, **kwargs):
        self.command = command
        self.pid = 321
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def inventory() -> RigInventory:
    gpus = [
        GpuDevice(i, f"0000:0{i + 1}:00.0", "nvidia", "RTX Test 8GB", 8 * 1024**3, 3, 1, "cuda", True, True)
        for i in range(6)
    ]
    return RigInventory(1, "2026-09-29T00:00:00Z", "linux", 6, 48 * 1024**3, gpus, True)


class TestModelEngineService(unittest.TestCase):
    def test_starts_verified_model_on_loopback_with_all_six_gpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "model.gguf"
            artifact.write_bytes(b"GGUF" + b"x" * 64)
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            process = FakeProcess([])

            def factory(command, **kwargs):
                process.command = command
                return process

            service = ModelEngineService(
                model_root=root,
                inventory_provider=inventory,
                executable=str(root / "llama-server"),
                process_factory=factory,
                startup_timeout_seconds=0.2,
            )
            (root / "llama-server").write_bytes(b"binary")
            with patch.object(service, "_health", return_value=True):
                status = service.start(EngineModel("test/model", artifact, digest, artifact.stat().st_size, 64))

            self.assertTrue(status["ready"])
            self.assertEqual(status["allocation"]["total_gpus"], 6)
            self.assertEqual(process.command[process.command.index("--host") + 1], "127.0.0.1")
            self.assertNotIn("--device", process.command)
            self.assertEqual(len(process.command[process.command.index("--tensor-split") + 1].split(",")), 6)

    def test_rejects_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "model.gguf"
            artifact.write_bytes(b"GGUFpayload")
            service = ModelEngineService(model_root=root, inventory_provider=inventory)
            with self.assertRaisesRegex(ModelEngineError, "SHA-256"):
                service.start(EngineModel("test/model", artifact, "0" * 64, artifact.stat().st_size, 32))

    def test_rejects_artifact_outside_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            artifact = Path(other) / "model.gguf"
            artifact.write_bytes(b"GGUFpayload")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            service = ModelEngineService(model_root=Path(tmp), inventory_provider=inventory)
            with self.assertRaisesRegex(ModelEngineError, "beneath"):
                service.start(EngineModel("test/model", artifact, digest, artifact.stat().st_size, 32))


if __name__ == "__main__":
    unittest.main()
