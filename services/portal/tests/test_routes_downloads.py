"""Unit tests for the ComputeMesh Dynamic Download & Script Generator Subsystem."""
import unittest

from services.portal.routes_downloads import (
    build_ollama_reset_bat,
    build_ollama_reset_sh,
    build_ollama_starter_bat,
    build_ollama_starter_sh,
    get_download_file_response,
)


class TestRoutesDownloads(unittest.TestCase):
    def test_build_ollama_starter_bat_embeds_owner_key(self) -> None:
        key = "owk_customer_test_12345"
        bat = build_ollama_starter_bat(owner_key=key, cluster_url="https://mesh.inetconnector.com")
        self.assertIn("set OLLAMA_HOST=0.0.0.0:11434", bat)
        self.assertIn("set OLLAMA_ORIGINS=*", bat)
        self.assertIn(key, bat)
        self.assertIn("https://mesh.inetconnector.com", bat)
        self.assertIn("windows_tray_app.py", bat)

    def test_build_ollama_starter_sh_embeds_owner_key(self) -> None:
        key = "owk_customer_linux_67890"
        sh = build_ollama_starter_sh(owner_key=key, cluster_url="https://mesh.inetconnector.com")
        self.assertIn('export OLLAMA_HOST="0.0.0.0:11434"', sh)
        self.assertIn('export OLLAMA_ORIGINS="*"', sh)
        self.assertIn(key, sh)
        self.assertIn("node_daemon.py", sh)

    def test_build_ollama_reset_scripts_clear_environment(self) -> None:
        bat_reset = build_ollama_reset_bat()
        self.assertIn("set OLLAMA_HOST=", bat_reset)
        self.assertIn("reg delete", bat_reset)
        self.assertIn("ollama_mesh_bridge.py reset", bat_reset)

        sh_reset = build_ollama_reset_sh()
        self.assertIn("unset OLLAMA_HOST", sh_reset)
        self.assertIn("unset OLLAMA_ORIGINS", sh_reset)
        self.assertIn("pkill -f", sh_reset)

    def test_get_download_file_response_dispatcher(self) -> None:
        # Starter for Windows
        content, name, mime = get_download_file_response("starter", "windows", "owk_123")
        self.assertEqual(name, "OLLAMA-MESH-START.bat")
        self.assertEqual(mime, "application/x-bat")
        self.assertIn("owk_123", content)

        # Starter for Linux
        content_sh, name_sh, mime_sh = get_download_file_response("starter", "linux", "owk_456")
        self.assertEqual(name_sh, "ollama-mesh-start.sh")
        self.assertEqual(mime_sh, "application/x-sh")
        self.assertIn("owk_456", content_sh)

        # Reset for Windows
        res_bat, res_bat_name, res_bat_mime = get_download_file_response("reset", "windows")
        self.assertEqual(res_bat_name, "OLLAMA-RESET-DEFAULT.bat")
        self.assertEqual(res_bat_mime, "application/x-bat")

        # Reset for Linux
        res_sh, res_sh_name, res_sh_mime = get_download_file_response("reset", "linux")
        self.assertEqual(res_sh_name, "ollama-reset-default.sh")
        self.assertEqual(res_sh_mime, "application/x-sh")


if __name__ == "__main__":
    unittest.main()
