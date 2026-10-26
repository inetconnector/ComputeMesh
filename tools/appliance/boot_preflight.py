"""Fail-closed NodeOS boot checks for enrollment, persistence and runtime."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from tools.security.node_key_storage import load_node_private_key


class PreflightError(RuntimeError):
    pass


def _clear_ready_marker(path: Path | None) -> None:
    if path is None:
        return
    if path.is_symlink():
        raise PreflightError("preflight ready marker is a symlink")
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise PreflightError("cannot clear stale preflight ready marker") from exc


def _write_ready_marker(path: Path) -> None:
    if path.is_symlink():
        raise PreflightError("preflight ready marker is a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("x", encoding="ascii") as handle:
            handle.write("ready\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(0o644)
    except OSError as exc:
        raise PreflightError("cannot persist preflight ready marker") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _check_persistence() -> None:
    configured = os.environ.get("COMPUTEMESH_PERSISTENCE_MOUNT", "").strip()
    command = ["findmnt", "-rn", "-t", "ext4", "-o", "LABEL,TARGET"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("persistence inspection unavailable") from exc
    lines = result.stdout.splitlines()
    if configured:
        if not Path(configured).is_dir():
            raise PreflightError("configured persistence mount is missing")
        if not any(line.startswith(f"persistence {configured}") for line in lines):
            raise PreflightError("configured persistence mount is not an ext4 persistence filesystem")
    elif not any(line.split(maxsplit=1)[0] == "persistence" for line in lines if line.strip()):
        raise PreflightError("ext4 filesystem labelled persistence is not mounted")


def run_preflight(
    *,
    env_path: Path = Path("/etc/computemesh/provider.env"),
    key_path: Path | None = None,
    ca_path: Path | None = None,
    require_hardware: bool = True,
    ready_file: Path | None = None,
) -> None:
    _clear_ready_marker(ready_file)
    if env_path.is_symlink() or not env_path.is_file():
        raise PreflightError("provider.env is not provisioned")
    env = _parse_env(env_path)
    required = (
        "COMPUTEMESH_NODE_ID",
        "COMPUTEMESH_CONTROL_HOST",
        "COMPUTEMESH_CONTROL_PORT",
        "COMPUTEMESH_CONTROL_SERVER_HOSTNAME",
        "COMPUTEMESH_CONTROL_CA_FILE",
        "COMPUTEMESH_NODE_PRIVATE_KEY",
        "COMPUTEMESH_NODE_AUTH_TOKEN_PATH",
        "COMPUTEMESH_NODE_PROFILE",
        "COMPUTEMESH_NODE_PREFILL",
        "COMPUTEMESH_NODE_DECODE",
    )
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise PreflightError("provider.env lacks required enrollment fields")
    if any(value in {"node_replace_me", "control.example.invalid", "replace_me"} for value in env.values()):
        raise PreflightError("provider.env still contains a template placeholder")
    paths = [Path(env["COMPUTEMESH_NODE_PRIVATE_KEY"]), Path(env["COMPUTEMESH_CONTROL_CA_FILE"])]
    if key_path is not None:
        paths[0] = key_path
    if ca_path is not None:
        paths[1] = ca_path
    token_path = Path(env["COMPUTEMESH_NODE_AUTH_TOKEN_PATH"])
    if any(
        str(path).startswith(("/boot", "/live", "/run/live"))
        for path in (*paths, token_path)
    ):
        raise PreflightError("identity or CA material must not be stored on the live/FAT32 boot area")
    try:
        control_port = int(env["COMPUTEMESH_CONTROL_PORT"])
    except ValueError as exc:
        raise PreflightError("provider control port is invalid") from exc
    if not 1 <= control_port <= 65535:
        raise PreflightError("provider control port is invalid")
    try:
        load_node_private_key(paths[0])
    except Exception as exc:  # noqa: BLE001 - convert to one safe diagnostic
        raise PreflightError("persistent node private key is unavailable") from exc
    if paths[1].is_symlink() or not paths[1].is_file():
        raise PreflightError("control-plane CA file is unavailable")
    if token_path.is_symlink() or not token_path.is_file():
        raise PreflightError("persistent node authentication token is unavailable")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token.startswith("cm_tunnel_") or not token[10:].isalnum():
        raise PreflightError("persistent node authentication token is invalid")
    for name in ("COMPUTEMESH_NODE_PROFILE", "COMPUTEMESH_NODE_PREFILL", "COMPUTEMESH_NODE_DECODE"):
        if not Path(env[name]).is_file():
            raise PreflightError("enrolled node evidence file is unavailable")
    if shutil.which("llama-server") is None or shutil.which("vulkaninfo") is None:
        raise PreflightError("llama-server and vulkaninfo are required")
    try:
        llama = subprocess.run(["llama-server", "--version"], capture_output=True, text=True, timeout=10, check=False)
        if llama.returncode != 0 or not llama.stdout.strip() and not llama.stderr.strip():
            raise PreflightError("llama-server runtime check failed")
        if require_hardware:
            vulkan = subprocess.run(["vulkaninfo", "--summary"], capture_output=True, text=True, timeout=15, check=False)
            if vulkan.returncode != 0:
                raise PreflightError("Vulkan runtime check failed")
    except (OSError, subprocess.SubprocessError) as exc:
        raise PreflightError("inference runtime check failed") from exc
    _check_persistence()
    _write_ready_marker(ready_file) if ready_file is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path("/etc/computemesh/provider.env"))
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--allow-no-hardware", action="store_true", help="local software test only")
    args = parser.parse_args(argv)
    try:
        run_preflight(
            env_path=args.env,
            require_hardware=not args.allow_no_hardware,
            ready_file=args.ready_file,
        )
    except PreflightError as exc:
        print(f"NodeOS preflight failed: {exc}", file=sys.stderr)
        return 1
    print("NodeOS preflight passed: enrolled identity, persistence and runtime are ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
