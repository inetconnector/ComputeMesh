"""Install and configure Cline for the local ComputeMesh Windows node.

Cline is a Visual Studio Code extension, not a standalone ``Cline.exe``.
This module keeps the integration independent from tkinter so it can be
verified without starting the provider UI.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLINE_EXTENSION_ID = "saoudrizwan.claude-dev"
COMPUTEMESH_CLINE_BRIDGE_ID = "computemesh.cline-workspace-bridge"
COMPUTEMESH_CLINE_BRIDGE_VERSION = "1.0.2"
COMPUTEMESH_PROVIDER_ID = "openai"
COMPUTEMESH_MODEL_PROVIDER_ID = "openai-compatible"
LEGACY_COMPUTEMESH_PROVIDER_ID = "computemesh"
COMPUTEMESH_BASE_URL = "http://127.0.0.1:8080/v1"
COMPUTEMESH_MODEL_ID = "auto"
VSCODE_USER_INSTALLER_URL_X64 = "https://update.code.visualstudio.com/latest/win32-x64-user/stable"
VSCODE_USER_INSTALLER_URL_ARM64 = "https://update.code.visualstudio.com/latest/win32-arm64-user/stable"


class ClineIntegrationError(RuntimeError):
    """Raised when VS Code or Cline could not be installed or configured."""


@dataclass(frozen=True)
class ClineIntegrationResult:
    vscode_executable: Path
    vscode_installed: bool
    extension_installed: bool
    bridge_installed: bool
    configuration_directory: Path


def _candidate_vscode_executables(env: dict[str, str] | None = None) -> list[Path]:
    values = os.environ if env is None else env
    local_app_data = Path(values.get("LOCALAPPDATA", ""))
    program_files = Path(values.get("ProgramFiles", ""))
    program_files_x86 = Path(values.get("ProgramFiles(x86)", ""))
    candidates = [
        local_app_data / "Programs" / "Microsoft VS Code" / "Code.exe",
        program_files / "Microsoft VS Code" / "Code.exe",
        program_files_x86 / "Microsoft VS Code" / "Code.exe",
    ]
    command = shutil.which("code") or shutil.which("code.exe")
    if command:
        candidates.insert(0, Path(command))
    return candidates


def find_vscode_executable(env: dict[str, str] | None = None) -> Path | None:
    """Return a usable VS Code executable from standard Windows locations."""
    for candidate in _candidate_vscode_executables(env):
        if candidate.is_file():
            return candidate
    return None


def _vscode_installer_url() -> str:
    return VSCODE_USER_INSTALLER_URL_ARM64 if platform.machine().lower() in {"arm64", "aarch64"} else VSCODE_USER_INSTALLER_URL_X64


def install_vscode_user(
    *,
    downloader: Callable[[str, str], Any] = urllib.request.urlretrieve,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Install the official per-user VS Code build and return ``Code.exe``."""
    if os.name != "nt":
        raise ClineIntegrationError("VS Code can only be installed automatically on Windows.")

    with tempfile.TemporaryDirectory(prefix="computemesh-vscode-") as temp_dir:
        installer = Path(temp_dir) / "VSCodeUserSetup.exe"
        downloader(_vscode_installer_url(), str(installer))
        if not installer.is_file() or installer.stat().st_size < 1_000_000:
            raise ClineIntegrationError("The downloaded VS Code installer is missing or incomplete.")
        with installer.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise ClineIntegrationError("The downloaded VS Code installer is not a Windows executable.")

        completed = runner(
            [
                str(installer),
                "/VERYSILENT",
                "/NORESTART",
                "/MERGETASKS=!runcode",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown installer error").strip()
            raise ClineIntegrationError(f"VS Code installation failed: {detail}")

    executable = find_vscode_executable()
    if executable is None:
        raise ClineIntegrationError("VS Code was installed, but Code.exe could not be found.")
    return executable


def _vscode_cli_executable(vscode_executable: Path) -> Path:
    """Resolve the command-line wrapper belonging to a VS Code GUI binary."""
    executable = Path(vscode_executable)
    if os.name != "nt" or executable.suffix.lower() in {".cmd", ".bat"}:
        return executable

    cli = executable.parent / "bin" / "code.cmd"
    return cli if cli.is_file() else executable


def _run_vscode_cli(vscode_executable: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    cli_executable = _vscode_cli_executable(vscode_executable)
    try:
        return subprocess.run(
            [str(cli_executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClineIntegrationError(f"VS Code command failed: {exc}") from exc


def is_cline_extension_installed(vscode_executable: Path) -> bool:
    completed = _run_vscode_cli(vscode_executable, "--list-extensions")
    if completed.returncode != 0:
        return False
    extensions = {line.strip().lower() for line in completed.stdout.splitlines()}
    return CLINE_EXTENSION_ID.lower() in extensions


def _installed_extension_versions(vscode_executable: Path) -> dict[str, str]:
    completed = _run_vscode_cli(vscode_executable, "--list-extensions", "--show-versions")
    if completed.returncode != 0:
        return {}
    versions: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        extension_id, separator, version = line.strip().rpartition("@")
        if separator and extension_id and version:
            versions[extension_id.lower()] = version
    return versions


def install_cline_extension(vscode_executable: Path) -> None:
    """Install Cline from the official Visual Studio Marketplace."""
    completed = _run_vscode_cli(
        vscode_executable,
        "--install-extension",
        CLINE_EXTENSION_ID,
        "--force",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown extension error").strip()
        raise ClineIntegrationError(f"Cline extension installation failed: {detail}")
    if not is_cline_extension_installed(vscode_executable):
        raise ClineIntegrationError("VS Code completed the install command, but Cline is not registered.")


def _create_cline_bridge_vsix(destination: Path) -> None:
    """Create the dependency-free extension that restores Cline after a folder reload."""
    package = {
        "name": "cline-workspace-bridge",
        "displayName": "ComputeMesh Cline Workspace Bridge",
        "description": "Keeps the opted-in Cline view visible after VS Code workspace reloads.",
        "version": COMPUTEMESH_CLINE_BRIDGE_VERSION,
        "publisher": "computemesh",
        "engines": {"vscode": "^1.74.0"},
        "categories": ["Other"],
        "activationEvents": ["onStartupFinished"],
        "main": "./extension.js",
        "extensionDependencies": [CLINE_EXTENSION_ID],
    }
    extension_js = r'''const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");

function integrationEnabled() {
  try {
    const configPath = path.join(os.homedir(), ".computemesh", "provider_config.json");
    const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    return config.cline_vscode === true;
  } catch {
    return false;
  }
}

function writeStatus(status, detail) {
  try {
    const statusPath = path.join(os.homedir(), ".computemesh", "cline_bridge_status.json");
    fs.writeFileSync(statusPath, JSON.stringify({
      version: "__BRIDGE_VERSION__",
      status,
      detail,
      updated_at: new Date().toISOString()
    }, null, 2));
  } catch {
    // Status reporting must never block the editor.
  }
}

async function activate() {
  if (!integrationEnabled()) {
    return;
  }
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const commands = await vscode.commands.getCommands(true);
    if (commands.includes("cline.focusChatInput")) {
      try {
        await vscode.commands.executeCommand("cline.focusChatInput");
        writeStatus("ready", "Cline view restored after VS Code workspace startup.");
        console.log("[ComputeMesh Cline Bridge] Cline view restored.");
      } catch (error) {
        writeStatus("error", String(error));
        console.error("[ComputeMesh Cline Bridge] Could not restore Cline view.", error);
      }
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

exports.activate = activate;
exports.deactivate = function deactivate() {};
'''.replace("__BRIDGE_VERSION__", COMPUTEMESH_CLINE_BRIDGE_VERSION)
    manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="cline-workspace-bridge" Version="{COMPUTEMESH_CLINE_BRIDGE_VERSION}" Publisher="computemesh" />
    <DisplayName>ComputeMesh Cline Workspace Bridge</DisplayName>
    <Description xml:space="preserve">Restores the opted-in Cline view after workspace reloads.</Description>
    <Tags>computemesh,cline</Tags>
    <Categories>Other</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.74.0" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="{CLINE_EXTENSION_ID}" />
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" /></Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
'''
    content_types = '''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json" />
  <Default Extension="js" ContentType="application/javascript" />
  <Default Extension="vsixmanifest" ContentType="text/xml" />
</Types>
'''
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extension/package.json", f"{json.dumps(package, indent=2)}\n")
        archive.writestr("extension/extension.js", extension_js)
        archive.writestr("extension.vsixmanifest", manifest)
        archive.writestr("[Content_Types].xml", content_types)


def ensure_cline_workspace_bridge(vscode_executable: Path) -> bool:
    """Install or update the helper that reopens Cline after workspace reloads."""
    installed = _installed_extension_versions(vscode_executable)
    if installed.get(COMPUTEMESH_CLINE_BRIDGE_ID) == COMPUTEMESH_CLINE_BRIDGE_VERSION:
        return False

    with tempfile.TemporaryDirectory(prefix="computemesh-cline-bridge-") as temp_dir:
        vsix_path = Path(temp_dir) / "computemesh-cline-workspace-bridge.vsix"
        _create_cline_bridge_vsix(vsix_path)
        completed = _run_vscode_cli(
            vscode_executable,
            "--install-extension",
            str(vsix_path),
            "--force",
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown extension error").strip()
        raise ClineIntegrationError(f"ComputeMesh Cline bridge installation failed: {detail}")
    installed = _installed_extension_versions(vscode_executable)
    if installed.get(COMPUTEMESH_CLINE_BRIDGE_ID) != COMPUTEMESH_CLINE_BRIDGE_VERSION:
        raise ClineIntegrationError("VS Code installed the Cline bridge, but did not register it.")
    return True


def _read_json_object(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClineIntegrationError(f"Existing Cline configuration is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ClineIntegrationError(f"Existing Cline configuration is not a JSON object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(f"{json.dumps(value, indent=2)}\n", encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def discover_computemesh_model() -> str:
    """Prefer a locally installed coding model and fall back to node-side auto selection."""
    try:
        with urllib.request.urlopen(f"{COMPUTEMESH_BASE_URL}/models", timeout=5) as response:
            payload = json.load(response)
        model_ids = [
            item["id"].strip()
            for item in payload.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        ]
    except (OSError, ValueError, TypeError):
        return COMPUTEMESH_MODEL_ID
    if not model_ids:
        return COMPUTEMESH_MODEL_ID
    return min(model_ids, key=lambda model_id: ("coder" not in model_id.lower(), model_ids.index(model_id)))


def configure_cline_for_computemesh(home: Path | None = None, *, model_id: str | None = None) -> Path:
    """Add a dedicated ComputeMesh provider without replacing other providers."""
    user_home = Path.home() if home is None else Path(home)
    selected_model_id = model_id or discover_computemesh_model()
    data_dir = user_home / ".cline" / "data"
    settings_dir = data_dir / "settings"
    providers_path = settings_dir / "providers.json"
    models_path = settings_dir / "models.json"
    global_state_path = data_dir / "globalState.json"
    updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    providers = _read_json_object(
        providers_path,
        default={"version": 1, "modes": {}, "providers": {}},
    )
    if providers.get("version", 1) != 1 or not isinstance(providers.get("providers", {}), dict):
        raise ClineIntegrationError(f"Unsupported Cline provider configuration: {providers_path}")
    providers.setdefault("version", 1)
    providers.setdefault("modes", {})
    providers.setdefault("providers", {})
    providers["providers"].pop(LEGACY_COMPUTEMESH_PROVIDER_ID, None)
    providers["lastUsedProvider"] = COMPUTEMESH_PROVIDER_ID
    providers["providers"][COMPUTEMESH_PROVIDER_ID] = {
        "settings": {
            "provider": COMPUTEMESH_PROVIDER_ID,
            "apiKey": "computemesh-local",
            "model": selected_model_id,
            "protocol": "openai-chat",
            "client": "openai-compatible",
            "baseUrl": COMPUTEMESH_BASE_URL,
            "timeout": 300000,
            "reasoning": {"enabled": False},
            "capabilities": ["streaming", "tools"],
        },
        "updatedAt": updated_at,
        "tokenSource": "manual",
    }

    models = _read_json_object(models_path, default={"version": 1, "providers": {}})
    if models.get("version", 1) != 1 or not isinstance(models.get("providers", {}), dict):
        raise ClineIntegrationError(f"Unsupported Cline model configuration: {models_path}")
    models.setdefault("version", 1)
    models.setdefault("providers", {})
    models["providers"].pop(LEGACY_COMPUTEMESH_PROVIDER_ID, None)
    models["providers"][COMPUTEMESH_MODEL_PROVIDER_ID] = {
        "provider": {
            "name": "ComputeMesh Local Node",
            "baseUrl": COMPUTEMESH_BASE_URL,
            "defaultModelId": selected_model_id,
            "protocol": "openai-chat",
            "client": "openai-compatible",
            "capabilities": ["streaming", "tools"],
            "modelsSourceUrl": f"{COMPUTEMESH_BASE_URL}/models",
        },
        "models": {
            selected_model_id: {
                "name": "ComputeMesh Auto",
                "contextWindow": 128000,
                "maxTokens": 8192,
                "capabilities": ["streaming", "tools"],
            }
        },
    }

    global_state = _read_json_object(global_state_path, default={})
    global_state.update(
        {
            "planModeApiProvider": COMPUTEMESH_PROVIDER_ID,
            "actModeApiProvider": COMPUTEMESH_PROVIDER_ID,
            "planModeApiModelId": selected_model_id,
            "actModeApiModelId": selected_model_id,
            "planModeOpenAiModelId": selected_model_id,
            "actModeOpenAiModelId": selected_model_id,
            "openAiBaseUrl": COMPUTEMESH_BASE_URL,
            "mode": "act",
            "welcomeViewCompleted": True,
        }
    )

    _write_json_atomic(providers_path, providers)
    _write_json_atomic(models_path, models)
    _write_json_atomic(global_state_path, global_state)
    return settings_dir


def ensure_cline_integration(*, allow_vscode_install: bool) -> ClineIntegrationResult:
    """Ensure VS Code, the Cline extension, and ComputeMesh provider exist."""
    vscode_executable = find_vscode_executable()
    vscode_installed = False
    if vscode_executable is None:
        if not allow_vscode_install:
            raise ClineIntegrationError("Visual Studio Code is required for Cline.")
        vscode_executable = install_vscode_user()
        vscode_installed = True

    extension_installed = False
    if not is_cline_extension_installed(vscode_executable):
        install_cline_extension(vscode_executable)
        extension_installed = True
    bridge_installed = ensure_cline_workspace_bridge(vscode_executable)
    configuration_directory = configure_cline_for_computemesh()
    return ClineIntegrationResult(
        vscode_executable=vscode_executable,
        vscode_installed=vscode_installed,
        extension_installed=extension_installed,
        bridge_installed=bridge_installed,
        configuration_directory=configuration_directory,
    )


def launch_cline_in_vscode(vscode_executable: Path) -> None:
    """Open VS Code; the installed Cline activity-bar view activates at startup."""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            [str(vscode_executable), "--new-window"],
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        raise ClineIntegrationError(f"VS Code could not be started: {exc}") from exc
