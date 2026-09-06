"""Unit tests for the ComputeMesh Ollama Mesh Bridge and Pool Configurator."""
import os
import unittest
from unittest.mock import patch, MagicMock

from tools.appliance.ollama_mesh_bridge import (
    detect_ollama_executable,
    get_installed_ollama_models,
    get_ollama_bridge_status,
    is_ollama_running,
    reset_ollama_to_default_environment,
)


class TestOllamaMeshBridge(unittest.TestCase):
    def test_reset_ollama_environment_cleans_overrides(self) -> None:
        os.environ["OLLAMA_HOST"] = "0.0.0.0:11434"
        os.environ["OLLAMA_ORIGINS"] = "*"
        os.environ["OLLAMA_KEEP_ALIVE"] = "24h"

        res = reset_ollama_to_default_environment()
        self.assertEqual(res["status"], "ok")
        self.assertNotIn("OLLAMA_HOST", os.environ)
        self.assertNotIn("OLLAMA_ORIGINS", os.environ)
        self.assertNotIn("OLLAMA_KEEP_ALIVE", os.environ)

    @patch("tools.appliance.ollama_mesh_bridge.urllib.request.urlopen")
    def test_is_ollama_running_when_healthy(self, mock_urlopen) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.assertTrue(is_ollama_running("http://127.0.0.1:11434"))

    @patch("tools.appliance.ollama_mesh_bridge.urllib.request.urlopen")
    def test_get_installed_ollama_models_parses_tags(self, mock_urlopen) -> None:
        fake_json = b'{"models": [{"name": "qwen2.5:1.5b", "size": 1024000, "details": {"parameter_size": "1.5B"}}]}'
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = fake_json
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        models = get_installed_ollama_models("http://127.0.0.1:11434")
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "qwen2.5:1.5b")
        self.assertEqual(models[0].parameter_size, "1.5B")

    def test_get_ollama_bridge_status_structure(self) -> None:
        st = get_ollama_bridge_status("http://127.0.0.1:99999")
        self.assertIsInstance(st.installed, bool)
        self.assertFalse(st.running)
        self.assertEqual(st.models, [])


if __name__ == "__main__":
    unittest.main()
