"""Provision a NodeOS node through the existing signed gateway heartbeat path.

The bundle is a one-time operator handoff. It is never logged. The script
creates or reuses the persistent Ed25519 key, proves possession to the existing
``/api/v1/node/heartbeat`` endpoint with the supplied enrollment token, and
only then writes ``provider.env``. No private or owner key is copied to the
control plane.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import serialization

from tools.appliance.boot_preflight import PreflightError, validate_node_evidence
from tools.appliance.node_identity import NodeIdentityError, validate_node_id
from tools.security.node_auth_token_storage import persist_node_auth_token
from tools.security.node_key_storage import (
    get_or_create_node_private_key,
    secure_path_for_service,
    sign_node_heartbeat,
)


class EnrollmentError(RuntimeError):
    pass


def _activate_nodeos_services(provider_env: Path) -> None:
    """Run the existing preflight and hand control to systemd after enrollment."""
    nodeos_mode = os.environ.get("COMPUTEMESH_NODEOS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not nodeos_mode:
        return

    marker = Path(
        os.environ.get(
            "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER",
            "/run/computemesh/node-preflight.ok",
        )
    )
    try:
        from tools.appliance.boot_preflight import run_preflight

        run_preflight(env_path=provider_env, ready_file=marker)
    except Exception as exc:  # noqa: BLE001 - enrollment diagnostics stay secret-free
        raise EnrollmentError("enrollment completed but NodeOS preflight failed") from exc

    for unit in (
        "computemesh-node-preflight.service",
        "computemesh-node.service",
        "computemesh-node-heartbeat.service",
    ):
        try:
            result = subprocess.run(
                ["systemctl", "restart", unit],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise EnrollmentError("enrollment completed but NodeOS services could not be activated") from exc
        if result.returncode != 0:
            raise EnrollmentError("enrollment completed but a NodeOS service failed to start")


def _atomic_write(path: Path, text: str, mode: int) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise EnrollmentError("refusing symlinked provisioning path")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            import os
            os.fsync(handle.fileno())
        temp.replace(path)
        if sys.platform != "win32":
            path.chmod(mode)
    finally:
        temp.unlink(missing_ok=True)


def _require_text(bundle: dict[str, object], name: str, *, max_length: int = 512) -> str:
    value = bundle.get(name)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= max_length:
        raise EnrollmentError(f"enrollment bundle field {name} is invalid")
    return value.strip()


def _provider_control_endpoint(
    bundle: dict[str, object],
    enrollment_url: str,
    *,
    enrollment_scheme: str,
) -> tuple[str, int, str, Path]:
    raw = bundle.get("provider_control")
    if raw is None:
        aliases = {
            "host": bundle.get("provider_control_host"),
            "port": bundle.get("provider_control_port"),
            "server_hostname": bundle.get("provider_control_server_hostname"),
            "ca_file": bundle.get("provider_control_ca_file"),
        }
        if not all(value is not None for value in aliases.values()):
            raise EnrollmentError(
                "enrollment bundle must provide a separate provider_control endpoint"
            )
        raw = aliases
    if not isinstance(raw, dict):
        raise EnrollmentError("provider_control must be an object")
    host = raw.get("host")
    server_hostname = raw.get("server_hostname")
    if not isinstance(host, str) or not 1 <= len(host.strip()) <= 253:
        raise EnrollmentError("provider_control host is invalid")
    if not isinstance(server_hostname, str) or not 1 <= len(server_hostname.strip()) <= 253:
        raise EnrollmentError("provider_control server_hostname is invalid")
    raw_port = raw.get("port")
    if isinstance(raw_port, bool):
        raise EnrollmentError("provider_control port is invalid")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise EnrollmentError("provider_control port is invalid") from exc
    if not 1 <= port <= 65535:
        raise EnrollmentError("provider_control port is invalid")
    ca_value = raw.get("ca_file")
    if not isinstance(ca_value, str) or not ca_value.strip():
        raise EnrollmentError("provider_control ca_file is invalid")
    ca_file = Path(ca_value.strip())
    if ca_file.is_symlink() or not ca_file.is_file():
        raise EnrollmentError("provider control CA file is unavailable")

    parsed = urlparse(enrollment_url)
    enrollment_port = parsed.port or (443 if enrollment_scheme == "https" else 80)
    if parsed.hostname and host.strip().lower() == parsed.hostname.lower() and port == enrollment_port:
        raise EnrollmentError("provider_control endpoint must be distinct from the enrollment endpoint")
    return host.strip(), port, server_hostname.strip(), ca_file


def _reject_live_path(path: Path, description: str) -> None:
    if str(path).startswith(("/boot", "/live", "/run/live")):
        raise EnrollmentError(f"{description} must be stored on persistent storage")


def enroll(bundle_path: Path, *, allow_insecure_localhost: bool = False) -> Path:
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise EnrollmentError("enrollment bundle is missing or symlinked")
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnrollmentError("enrollment bundle is unreadable") from exc
    if not isinstance(bundle, dict):
        raise EnrollmentError("enrollment bundle must be an object")

    try:
        node_id = validate_node_id(_require_text(bundle, "node_id", max_length=128))
    except NodeIdentityError as exc:
        raise EnrollmentError("enrollment bundle node_id is invalid") from exc
    auth_token = _require_text(bundle, "auth_token", max_length=256)
    if not auth_token.startswith("cm_tunnel_") or len(auth_token) < 32:
        raise EnrollmentError("enrollment auth_token has an invalid format")
    enrollment_token = _require_text(bundle, "enrollment_token", max_length=256)
    control_url = _require_text(bundle, "control_url", max_length=2048).rstrip("/")
    parsed = urlparse(control_url)
    if parsed.scheme != "https":
        if not allow_insecure_localhost or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise EnrollmentError("enrollment requires HTTPS; insecure mode is localhost-only")
    ca_file = Path(_require_text(bundle, "control_ca_file", max_length=1024))
    if ca_file.is_symlink() or not ca_file.is_file():
        raise EnrollmentError("control-plane CA file is unavailable")
    provider_host, provider_port, provider_server_hostname, provider_ca_file = _provider_control_endpoint(
        bundle,
        control_url,
        enrollment_scheme=parsed.scheme,
    )
    profile_path = Path(str(bundle.get("profile_path", "/var/lib/computemesh/evidence/node_profile.json")))
    prefill_path = Path(str(bundle.get("prefill_path", "/var/lib/computemesh/evidence/prefill.json")))
    decode_path = Path(str(bundle.get("decode_path", "/var/lib/computemesh/evidence/decode.json")))
    for evidence_path, description in (
        (profile_path, "node profile evidence"),
        (prefill_path, "prefill evidence"),
        (decode_path, "decode evidence"),
    ):
        _reject_live_path(evidence_path, description)
    try:
        validate_node_evidence(
            node_id=node_id,
            profile_path=profile_path,
            prefill_path=prefill_path,
            decode_path=decode_path,
        )
    except PreflightError as exc:
        raise EnrollmentError(
            "enrollment requires measured runtime evidence before gateway acceptance"
        ) from exc
    key_path = Path(bundle.get("private_key_path", "/var/lib/computemesh/node-ed25519.pem"))
    if not key_path.is_absolute():
        raise EnrollmentError("private key must use an absolute persistent path")
    _reject_live_path(key_path, "private key")
    private_key, _ = get_or_create_node_private_key(path=key_path)
    nodeos_mode = os.environ.get("COMPUTEMESH_NODEOS", "").strip().lower() in {"1", "true", "yes", "on"}
    if nodeos_mode:
        try:
            secure_path_for_service(key_path, "computemesh", mode=0o600)
        except Exception as exc:  # noqa: BLE001 - do not leak path/credential details
            raise EnrollmentError("private key cannot be assigned to the provider service") from exc
    public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    timestamp = int(time.time())
    nonce = f"enroll-{timestamp}-{node_id}"
    signature = sign_node_heartbeat(private_key, node_id, auth_token, timestamp, nonce=nonce, previous_node_id="")
    payload = {
        "node_id": node_id,
        "auth_token": auth_token,
        "enrollment_token": enrollment_token,
        "public_key": public_key,
        "signature": signature,
        "timestamp": timestamp,
        "nonce": nonce,
        "protocol_version": 2,
    }
    owner_key = bundle.get("owner_key")
    if isinstance(owner_key, str) and owner_key.strip():
        payload["owner_key"] = owner_key.strip()
    request = Request(
        control_url + "/api/v1/node/heartbeat",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "ComputeMesh-NodeOS-Enroller/1"},
        method="POST",
    )
    context = ssl.create_default_context(cafile=str(ca_file)) if parsed.scheme == "https" else None
    try:
        with urlopen(request, timeout=10, context=context) as response:  # noqa: S310 - URL is operator bundle input
            result = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (OSError, HTTPError, URLError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnrollmentError("control-plane enrollment request failed") from exc
    if not isinstance(result, dict) or result.get("status") != "ok" or result.get("node_id") != node_id:
        raise EnrollmentError("control-plane rejected enrollment")

    provider_env = Path(str(bundle.get("provider_env_path", "/etc/computemesh/provider.env")))
    _reject_live_path(provider_env, "provider environment")
    node_auth_token_path = Path(
        str(bundle.get("node_auth_token_path", "/var/lib/computemesh/node_auth_token.txt"))
    )
    _reject_live_path(node_auth_token_path, "node authentication token")
    try:
        persisted_token_path = persist_node_auth_token(auth_token, node_auth_token_path)
    except Exception as exc:  # noqa: BLE001 - keep enrollment diagnostics secret-free
        raise EnrollmentError("node authentication token cannot be persisted") from exc
    env_text = "\n".join(
        (
            "# Generated by computemesh-enroll; credentials are not stored here.",
            f"COMPUTEMESH_CONTROL_HOST={provider_host}",
            f"COMPUTEMESH_CONTROL_PORT={provider_port}",
            f"COMPUTEMESH_CONTROL_SERVER_HOSTNAME={provider_server_hostname}",
            f"COMPUTEMESH_CONTROL_CA_FILE={provider_ca_file}",
            f"COMPUTEMESH_NODE_ID={node_id}",
            f"COMPUTEMESH_NODE_PRIVATE_KEY={key_path}",
            f"COMPUTEMESH_NODE_AUTH_TOKEN_PATH={persisted_token_path}",
            f"COMPUTEMESH_NODE_PROFILE={profile_path}",
            f"COMPUTEMESH_NODE_PREFILL={prefill_path}",
            f"COMPUTEMESH_NODE_DECODE={decode_path}",
            "COMPUTEMESH_NODE_RPC_HOST=127.0.0.1",
            "COMPUTEMESH_NODE_RPC_PORT=50052",
            f"COMPUTEMESH_LLAMA_BUILD_NUMBER={bundle.get('llama_build_number', '0')}",
            f"COMPUTEMESH_LLAMA_BUILD_COMMIT={bundle.get('llama_build_commit', 'unknown')}",
            "COMPUTEMESH_NODEOS_INFERENCE_ENDPOINT=http://127.0.0.1:8081/v1/chat/completions",
            "COMPUTEMESH_NODEOS_ENVIRONMENT_ROOT=/var/lib/computemesh/agent-environments",
            "",
        )
    )
    _atomic_write(provider_env, env_text, 0o600)
    receipt = provider_env.parent / "enrollment.receipt.json"
    _atomic_write(
        receipt,
        json.dumps(
            {
                "node_id": node_id,
                "public_key": public_key,
                "provider_control_host": provider_host,
                "provider_control_port": provider_port,
                "provider_control_server_hostname": provider_server_hostname,
            },
            sort_keys=True,
        )
        + "\n",
        0o600,
    )
    if nodeos_mode:
        try:
            for path in (persisted_token_path, provider_env, receipt):
                secure_path_for_service(path, "computemesh", mode=0o600)
        except Exception as exc:  # noqa: BLE001 - keep enrollment diagnostics secret-free
            raise EnrollmentError("provider credentials cannot be assigned to the provider service") from exc
    _activate_nodeos_services(provider_env)
    bundle_path.unlink()
    return provider_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("/etc/computemesh/enrollment.json"))
    parser.add_argument("--allow-insecure-localhost", action="store_true")
    args = parser.parse_args(argv)
    try:
        enroll(args.bundle, allow_insecure_localhost=args.allow_insecure_localhost)
    except EnrollmentError as exc:
        print(f"Enrollment failed: {exc}", file=sys.stderr)
        return 1
    print("Enrollment completed; provider configuration is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
