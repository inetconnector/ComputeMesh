"""Tests for the optional Windows Cline and VS Code integration."""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from tools.appliance.windows_cline_integration import (
    CLINE_EXTENSION_ID,
    COMPUTEMESH_BASE_URL,
    COMPUTEMESH_CLINE_BRIDGE_ID,
    COMPUTEMESH_CLINE_BRIDGE_VERSION,
    COMPUTEMESH_MODEL_PROVIDER_ID,
    COMPUTEMESH_PROVIDER_ID,
    ClineIntegrationError,
    _create_cline_bridge_vsix,
    _run_vscode_cli,
    configure_cline_for_computemesh,
    discover_computemesh_model,
    ensure_cline_integration,
    ensure_cline_workspace_bridge,
    find_vscode_executable,
    install_cline_extension,
)


class TestWindowsClineIntegration(unittest.TestCase):
    def test_find_vscode_executable_uses_standard_user_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir)
            executable = local_app_data / "Programs" / "Microsoft VS Code" / "Code.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"MZ")

            with patch("tools.appliance.windows_cline_integration.shutil.which", return_value=None):
                found = find_vscode_executable(
                    {
                        "LOCALAPPDATA": str(local_app_data),
                        "ProgramFiles": str(local_app_data / "Program Files"),
                        "ProgramFiles(x86)": str(local_app_data / "Program Files (x86)"),
                    }
                )

            self.assertEqual(found, executable)

    def test_configuration_adds_dedicated_provider_and_preserves_existing_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            settings = home / ".cline" / "data" / "settings"
            settings.mkdir(parents=True)
            (settings / "providers.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "modes": {},
                        "lastUsedProvider": "existing",
                        "providers": {
                            "existing": {
                                "settings": {"provider": "existing", "apiKey": "keep-me"},
                                "updatedAt": "2026-01-01T00:00:00Z",
                                "tokenSource": "manual",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (settings / "models.json").write_text(
                json.dumps({"version": 1, "providers": {"existing": {"models": {}}}}),
                encoding="utf-8",
            )

            result = configure_cline_for_computemesh(home, model_id="auto")

            self.assertEqual(result, settings)
            providers = json.loads((settings / "providers.json").read_text(encoding="utf-8"))
            self.assertEqual(providers["providers"]["existing"]["settings"]["apiKey"], "keep-me")
            self.assertEqual(providers["lastUsedProvider"], COMPUTEMESH_PROVIDER_ID)
            compute_settings = providers["providers"][COMPUTEMESH_PROVIDER_ID]["settings"]
            self.assertEqual(compute_settings["baseUrl"], COMPUTEMESH_BASE_URL)
            self.assertEqual(compute_settings["client"], "openai-compatible")
            self.assertIn("tools", compute_settings["capabilities"])

            models = json.loads((settings / "models.json").read_text(encoding="utf-8"))
            self.assertIn("existing", models["providers"])
            compute_models = models["providers"][COMPUTEMESH_MODEL_PROVIDER_ID]
            self.assertEqual(compute_models["provider"]["modelsSourceUrl"], f"{COMPUTEMESH_BASE_URL}/models")
            self.assertIn("auto", compute_models["models"])

            global_state = json.loads(
                (home / ".cline" / "data" / "globalState.json").read_text(encoding="utf-8")
            )
            self.assertEqual(global_state["actModeApiProvider"], COMPUTEMESH_PROVIDER_ID)
            self.assertEqual(global_state["actModeApiModelId"], "auto")
            self.assertEqual(global_state["openAiBaseUrl"], COMPUTEMESH_BASE_URL)

    def test_model_discovery_prefers_installed_coder_model(self) -> None:
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read = Mock(
            return_value=json.dumps(
                {
                    "data": [
                        {"id": "gemma4:26b"},
                        {"id": "qwen2.5-coder:14b"},
                        {"id": "gemma3:4b"},
                    ]
                }
            ).encode("utf-8")
        )

        with patch("tools.appliance.windows_cline_integration.urllib.request.urlopen", return_value=response):
            selected = discover_computemesh_model()

        self.assertEqual(selected, "qwen2.5-coder:14b")

    def test_configuration_replaces_only_legacy_computemesh_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            settings = home / ".cline" / "data" / "settings"
            settings.mkdir(parents=True)
            (settings / "providers.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "modes": {},
                        "providers": {
                            "computemesh": {"settings": {"provider": "computemesh"}},
                            "existing": {"settings": {"provider": "existing"}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (settings / "models.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "providers": {
                            "computemesh": {"models": {}},
                            "existing": {"models": {}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            configure_cline_for_computemesh(home, model_id="auto")

            providers = json.loads((settings / "providers.json").read_text(encoding="utf-8"))["providers"]
            models = json.loads((settings / "models.json").read_text(encoding="utf-8"))["providers"]
            self.assertNotIn("computemesh", providers)
            self.assertNotIn("computemesh", models)
            self.assertIn("existing", providers)
            self.assertIn("existing", models)
            self.assertIn(COMPUTEMESH_PROVIDER_ID, providers)
            self.assertIn(COMPUTEMESH_MODEL_PROVIDER_ID, models)

    def test_configuration_refuses_to_destroy_invalid_existing_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            settings = home / ".cline" / "data" / "settings"
            settings.mkdir(parents=True)
            providers_path = settings / "providers.json"
            providers_path.write_text("not-json", encoding="utf-8")

            with self.assertRaises(ClineIntegrationError):
                configure_cline_for_computemesh(home, model_id="auto")

            self.assertEqual(providers_path.read_text(encoding="utf-8"), "not-json")

    def test_ensure_integration_installs_missing_dependencies_then_configures(self) -> None:
        vscode = Path("C:/Users/Test/AppData/Local/Programs/Microsoft VS Code/Code.exe")
        configuration = Path("C:/Users/Test/.cline/data/settings")
        with (
            patch(
                "tools.appliance.windows_cline_integration.find_vscode_executable",
                return_value=None,
            ),
            patch(
                "tools.appliance.windows_cline_integration.install_vscode_user",
                return_value=vscode,
            ) as install_vscode,
            patch(
                "tools.appliance.windows_cline_integration.is_cline_extension_installed",
                return_value=False,
            ),
            patch("tools.appliance.windows_cline_integration.install_cline_extension") as install_cline,
            patch(
                "tools.appliance.windows_cline_integration.ensure_cline_workspace_bridge",
                return_value=True,
            ) as install_bridge,
            patch(
                "tools.appliance.windows_cline_integration.configure_cline_for_computemesh",
                return_value=configuration,
            ) as configure,
        ):
            result = ensure_cline_integration(allow_vscode_install=True)

        install_vscode.assert_called_once_with()
        install_cline.assert_called_once_with(vscode)
        install_bridge.assert_called_once_with(vscode)
        configure.assert_called_once_with()
        self.assertTrue(result.vscode_installed)
        self.assertTrue(result.extension_installed)
        self.assertTrue(result.bridge_installed)
        self.assertEqual(result.configuration_directory, configuration)

    def test_extension_install_is_verified_after_marketplace_command(self) -> None:
        vscode = Path("C:/Program Files/Microsoft VS Code/Code.exe")
        completed = Mock(returncode=0, stdout="installed", stderr="")
        with (
            patch(
                "tools.appliance.windows_cline_integration._run_vscode_cli",
                return_value=completed,
            ) as run_cli,
            patch(
                "tools.appliance.windows_cline_integration.is_cline_extension_installed",
                return_value=True,
            ) as verify,
        ):
            install_cline_extension(vscode)

        run_cli.assert_called_once_with(
            vscode,
            "--install-extension",
            CLINE_EXTENSION_ID,
            "--force",
        )
        verify.assert_called_once_with(vscode)

    def test_vscode_cli_uses_code_cmd_next_to_gui_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir) / "Microsoft VS Code"
            vscode = install_dir / "Code.exe"
            cli = install_dir / "bin" / "code.cmd"
            cli.parent.mkdir(parents=True)
            vscode.write_bytes(b"MZ")
            cli.write_text("@echo off\n", encoding="utf-8")
            completed = Mock(returncode=0, stdout="", stderr="")

            with patch(
                "tools.appliance.windows_cline_integration.subprocess.run",
                return_value=completed,
            ) as run:
                result = _run_vscode_cli(vscode, "--list-extensions")

            self.assertIs(result, completed)
            self.assertEqual(run.call_args.args[0], [str(cli), "--list-extensions"])

    def test_official_extension_identifier_is_used(self) -> None:
        self.assertEqual(CLINE_EXTENSION_ID, "saoudrizwan.claude-dev")

    def test_workspace_bridge_package_reopens_cline_only_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vsix = Path(temp_dir) / "bridge.vsix"
            _create_cline_bridge_vsix(vsix)

            with zipfile.ZipFile(vsix) as archive:
                package = json.loads(archive.read("extension/package.json"))
                javascript = archive.read("extension/extension.js").decode("utf-8")

            self.assertEqual(package["publisher"], "computemesh")
            self.assertEqual(package["version"], COMPUTEMESH_CLINE_BRIDGE_VERSION)
            self.assertEqual(package["activationEvents"], ["onStartupFinished"])
            self.assertEqual(package["extensionDependencies"], [CLINE_EXTENSION_ID])
            self.assertIn('config.cline_vscode === true', javascript)
            self.assertIn('executeCommand("cline.focusChatInput")', javascript)
            self.assertIn("Cline view restored", javascript)
            self.assertIn('writeStatus("ready"', javascript)
            self.assertIn(f'version: "{COMPUTEMESH_CLINE_BRIDGE_VERSION}"', javascript)

    def test_workspace_bridge_is_not_reinstalled_at_current_version(self) -> None:
        vscode = Path("C:/Program Files/Microsoft VS Code/Code.exe")
        with (
            patch(
                "tools.appliance.windows_cline_integration._installed_extension_versions",
                return_value={COMPUTEMESH_CLINE_BRIDGE_ID: COMPUTEMESH_CLINE_BRIDGE_VERSION},
            ),
            patch("tools.appliance.windows_cline_integration._run_vscode_cli") as run_cli,
        ):
            installed = ensure_cline_workspace_bridge(vscode)

        self.assertFalse(installed)
        run_cli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
