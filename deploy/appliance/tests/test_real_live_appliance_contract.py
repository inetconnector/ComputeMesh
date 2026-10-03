from pathlib import Path
import unittest

from deploy.appliance.build_real_live_appliance import (
    DEFAULT_PERSISTENCE_SIZE_MIB,
    LLAMA_CPP_COMMIT,
    LLAMA_CPP_VERSION,
)


class TestRealLiveApplianceContract(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
