"""Unit tests for Windows Standalone Executable & Installer Packaging Engine."""
import tempfile
import unittest
from pathlib import Path

from deploy.windows.build_installer import (
    _pyinstaller_portal_data_options,
    _pyinstaller_tcl_tk_options,
    build_windows_standalone_bundle,
)


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

    def test_pyinstaller_bundle_declares_tcl_tk_runtime_data(self) -> None:
        options = _pyinstaller_tcl_tk_options()
        if not options:
            self.skipTest("Tcl/Tk bundle options are Windows-specific")
        self.assertIn("_tcl_data", options[1])
        self.assertIn("_tk_data", options[3])
        self.assertIn("_tkinter", options)

    def test_pyinstaller_bundle_includes_webui(self) -> None:
        options = _pyinstaller_portal_data_options()
        self.assertIn("portal/assets", options[1])
        self.assertIn("portal/webui", options[3])
        source = Path(options[3].split(";", 1)[0])
        self.assertTrue((source / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
