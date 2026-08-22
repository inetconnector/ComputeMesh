"""Unit tests for Windows Standalone Executable & Installer Packaging Engine."""
from pathlib import Path
import tempfile
import unittest

from deploy.windows.build_installer import build_windows_standalone_bundle


class TestWindowsBuildInstaller(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_exe = Path(self.temp_dir.name) / "ComputeMesh-Setup-x64.exe"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_standalone_bundle(self) -> None:
        result = build_windows_standalone_bundle(self.output_exe, version="1.0.1")
        self.assertTrue(self.output_exe.exists())
        self.assertGreater(result.file_size_bytes, 1000)
        self.assertEqual(len(result.sha256_hash), 64)
        self.assertEqual(result.manifest["version"], "1.0.1")
        self.assertEqual(result.manifest["platform"], "windows-x64")


if __name__ == "__main__":
    unittest.main()
