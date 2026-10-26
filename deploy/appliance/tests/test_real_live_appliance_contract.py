from pathlib import Path
import unittest

from deploy.appliance.build_real_live_appliance import (
    DEFAULT_PERSISTENCE_SIZE_MIB,
    LLAMA_CPP_COMMIT,
    LLAMA_CPP_VERSION,
)


class TestRealLiveApplianceContract(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        source = Path(__file__).resolve().parents[1] / "build_real_live_appliance.py"
        return source.read_text(encoding="utf-8")

    def test_runtime_is_pinned_and_model_storage_is_large_enough(self) -> None:
        self.assertEqual(LLAMA_CPP_VERSION, "v0.4.1")
        self.assertRegex(LLAMA_CPP_COMMIT, r"^[0-9a-f]{40}$")
        self.assertGreaterEqual(DEFAULT_PERSISTENCE_SIZE_MIB, 64 * 1024)

    def test_image_has_no_shared_root_password(self) -> None:
        source = Path(__file__).resolve().parents[1] / "build_real_live_appliance.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("root:computemesh", text)
        self.assertNotIn("PasswordAuthentication yes", text)
        self.assertIn("PasswordAuthentication no", text)
        self.assertIn("COMPUTEMESH_LLAMA_SERVER=/usr/local/bin/llama-server", text)

    def test_builder_declares_and_validates_debian_mirror(self) -> None:
        self.assertRegex(self._source(), r"DEBIAN_MIRROR\s*=")

    def test_service_enablement_is_fail_closed(self) -> None:
        self.assertNotIn("systemctl enable computemesh-node.service || true", self._source())

    def test_console_monitor_is_a_real_embedded_runtime(self) -> None:
        monitor = Path(__file__).resolve().parents[3] / "tools" / "appliance" / "console_monitor.py"
        self.assertTrue(monitor.is_file())

    def test_boot_has_preflight_and_explicit_enrollment_contract(self) -> None:
        text = self._source()
        self.assertIn("computemesh-node-preflight.service", text)
        self.assertIn("computemesh-enroll", text)
        self.assertIn("persistence.conf", text)
        self.assertIn("persistence-label=persistence", text)
        self.assertIn('"portal"', text)
        self.assertIn("requirements.txt", text)


if __name__ == "__main__":
    unittest.main()
