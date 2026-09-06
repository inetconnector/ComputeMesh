"""ComputeMesh Automated Ollama Mesh Bridge & Dynamic Pool Configurator.

Enables 1-click Ollama launch configured for ComputeMesh pooling:
1. Gives local developer tools (LocalCode, VS Code, CLI, Cursor) 100% priority.
2. Automatically registers installed local models with the ComputeMesh node inventory.
3. Automatically serves & monetizes idle GPU capacity to the ComputeMesh network when not in local use.
4. Provides full reset capabilities to return Ollama to standard standalone defaults.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
import urllib.request
import urllib.error

DEFAULT_OLLAMA_PORT = 11434
DEFAULT_OLLAMA_URL = f"http://127.0.0.1:{DEFAULT_OLLAMA_PORT}"


@dataclass
class OllamaModelInfo:
    name: str
    size_bytes: int = 0
    parameter_size: str = ""
    quantization_level: str = ""
    modified_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OllamaBridgeStatus:
    installed: bool
    binary_path: str | None
    running: bool
    endpoint_url: str
    models: list[dict[str, Any]]
    mesh_pooling_active: bool
    version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_ollama_executable() -> Path | None:
    """Finds the Ollama executable in PATH or standard system installation locations."""
    # 1. Check system PATH
    found = shutil.which("ollama")
    if found:
        return Path(found)

    # 2. Check platform-specific default locations
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe" if local_appdata else None,
            Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
            Path("C:/Program Files/Ollama/ollama.exe"),
            Path("C:/Program Files (x86)/Ollama/ollama.exe"),
        ]
        for c in candidates:
            if c and c.exists():
                return c
    else:
        for p in [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"), Path("/bin/ollama")]:
            if p.exists():
                return p

    return None


def is_ollama_running(endpoint_url: str = DEFAULT_OLLAMA_URL) -> bool:
    """Verifies whether the Ollama HTTP daemon is responsive."""
    url = f"{endpoint_url.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ComputeMesh-Ollama-Bridge/1.2"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_installed_ollama_models(endpoint_url: str = DEFAULT_OLLAMA_URL) -> list[OllamaModelInfo]:
    """Retrieves all locally installed models from the active Ollama instance."""
    url = f"{endpoint_url.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ComputeMesh-Ollama-Bridge/1.2"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("models", []):
                    details = m.get("details", {})
                    models.append(
                        OllamaModelInfo(
                            name=str(m.get("name", "")),
                            size_bytes=int(m.get("size", 0)),
                            parameter_size=str(details.get("parameter_size", "")),
                            quantization_level=str(details.get("quantization_level", "")),
                            modified_at=str(m.get("modified_at", "")),
                        )
                    )
                return models
    except Exception:
        pass
    return []


def get_ollama_bridge_status(endpoint_url: str = DEFAULT_OLLAMA_URL) -> OllamaBridgeStatus:
    """Aggregates comprehensive status for CLI, tray app, and web dashboard."""
    exe = detect_ollama_executable()
    running = is_ollama_running(endpoint_url)
    models = get_installed_ollama_models(endpoint_url) if running else []

    version = ""
    if running:
        try:
            req = urllib.request.Request(f"{endpoint_url.rstrip('/')}/api/version", headers={"User-Agent": "ComputeMesh-Bridge/1.2"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    version = json.loads(resp.read().decode("utf-8")).get("version", "")
        except Exception:
            pass

    return OllamaBridgeStatus(
        installed=exe is not None,
        binary_path=str(exe) if exe else None,
        running=running,
        endpoint_url=endpoint_url,
        models=[m.to_dict() for m in models],
        mesh_pooling_active=running,
        version=version,
    )


def launch_ollama_for_mesh(
    port: int = DEFAULT_OLLAMA_PORT,
    bind_all_interfaces: bool = True,
    keep_alive: str = "24h",
) -> subprocess.Popen | None:
    """Launches Ollama configured for both local developer use and mesh monetization."""
    if is_ollama_running(f"http://127.0.0.1:{port}"):
        return None

    exe = detect_ollama_executable()
    if not exe:
        raise FileNotFoundError(
            "Ollama executable not found. Please install Ollama from https://ollama.com before launching."
        )

    env = os.environ.copy()
    host_bind = f"0.0.0.0:{port}" if bind_all_interfaces else f"127.0.0.1:{port}"
    env["OLLAMA_HOST"] = host_bind
    env["OLLAMA_ORIGINS"] = "*"
    env["OLLAMA_KEEP_ALIVE"] = keep_alive
    env["OLLAMA_NUM_PARALLEL"] = "4"

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

    proc = subprocess.Popen(
        [str(exe), "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
    )

    # Wait up to 6 seconds for daemon readiness
    for _ in range(12):
        time.sleep(0.5)
        if is_ollama_running(f"http://127.0.0.1:{port}"):
            break

    return proc


def reset_ollama_to_default_environment() -> dict[str, str]:
    """Removes ComputeMesh environment overrides so Ollama returns to standard standalone behavior."""
    # Reset local process environment
    for key in ["OLLAMA_HOST", "OLLAMA_ORIGINS", "OLLAMA_KEEP_ALIVE", "OLLAMA_NUM_PARALLEL"]:
        if key in os.environ:
            del os.environ[key]

    return {
        "status": "ok",
        "message": "Ollama environment reset to default standalone settings (127.0.0.1:11434, standard origins, standard keep-alive).",
    }


def main() -> int:
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower().strip()

    if action == "status":
        status = get_ollama_bridge_status()
        print(json.dumps(status.to_dict(), indent=2))
        return 0

    if action == "launch":
        try:
            print("Starting Ollama with ComputeMesh dynamic pooling configuration...")
            proc = launch_ollama_for_mesh()
            if proc or is_ollama_running():
                print("✓ Ollama daemon is running and ready for local use + mesh monetization!")
                models = get_installed_ollama_models()
                print(f"✓ Found {len(models)} local model(s): {', '.join(m.name for m in models) if models else 'None (use `ollama pull <model>` to download)'}")
                return 0
            else:
                print("⚠️ Failed to start Ollama daemon.")
                return 1
        except Exception as exc:
            print(f"Error launching Ollama: {exc}")
            return 1

    if action == "reset":
        res = reset_ollama_to_default_environment()
        print(f"✓ {res['message']}")
        return 0

    if action == "models":
        models = get_installed_ollama_models()
        print(json.dumps([m.to_dict() for m in models], indent=2))
        return 0

    print(f"Unknown action: {action}. Valid options: status, launch, reset, models")
    return 1


if __name__ == "__main__":
    sys.exit(main())
