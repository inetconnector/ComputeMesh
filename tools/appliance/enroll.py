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
from pathlib import Path
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import serialization

from tools.security.node_key_storage import get_or_create_node_private_key, sign_node_heartbeat


class EnrollmentError(RuntimeError):
    pass


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


def enroll(bundle_path: Path, *, allow_insecure_localhost: bool = False) -> Path:
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise EnrollmentError("enrollment bundle is missing or symlinked")
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnrollmentError("enrollment bundle is unreadable") from exc
    if not isinstance(bundle, dict):
        raise EnrollmentError("enrollment bundle must be an object")

    node_id = _require_text(bundle, "node_id", max_length=128)
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
    key_path = Path(bundle.get("private_key_path", "/var/lib/computemesh/node-ed25519.pem"))
    if str(key_path).startswith(("/boot", "/live", "/run/live")):
        raise EnrollmentError("private key must be stored on persistent storage")
    private_key, _ = get_or_create_node_private_key(path=key_path)
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
    control_host = parsed.hostname or ""
    control_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    profile = str(bundle.get("profile_path", "/var/lib/computemesh/evidence/node_profile.json"))
    prefill = str(bundle.get("prefill_path", "/var/lib/computemesh/evidence/prefill.json"))
    decode = str(bundle.get("decode_path", "/var/lib/computemesh/evidence/decode.json"))
    env_text = "\n".join(
        (
            "# Generated by computemesh-enroll; credentials are not stored here.",
            f"COMPUTEMESH_CONTROL_HOST={control_host}",
            f"COMPUTEMESH_CONTROL_PORT={control_port}",
            f"COMPUTEMESH_CONTROL_CA_FILE={ca_file}",
            f"COMPUTEMESH_NODE_ID={node_id}",
            f"COMPUTEMESH_NODE_PRIVATE_KEY={key_path}",
            f"COMPUTEMESH_NODE_PROFILE={profile}",
            f"COMPUTEMESH_NODE_PREFILL={prefill}",
            f"COMPUTEMESH_NODE_DECODE={decode}",
            "COMPUTEMESH_NODE_RPC_HOST=127.0.0.1",
            "COMPUTEMESH_NODE_RPC_PORT=50052",
            f"COMPUTEMESH_LLAMA_BUILD_NUMBER={bundle.get('llama_build_number', '0')}",
            f"COMPUTEMESH_LLAMA_BUILD_COMMIT={bundle.get('llama_build_commit', 'unknown')}",
            "COMPUTEMESH_NODEOS_INFERENCE_ENDPOINT=http://127.0.0.1:8081/v1/chat/completions",
            "COMPUTEMESH_NODEOS_ENVIRONMENT_ROOT=/var/lib/computemesh/agent-environments",
            "",
        )
    )
    _atomic_write(provider_env, env_text, 0o640)
    receipt = provider_env.parent / "enrollment.receipt.json"
    _atomic_write(
        receipt,
        json.dumps({"node_id": node_id, "public_key": public_key, "control_host": control_host}, sort_keys=True) + "\n",
        0o640,
    )
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
