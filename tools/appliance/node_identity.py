"""Canonical persisted NodeOS identity resolution.

The boot configuration contains display and network defaults.  Once a node has
been enrolled, ``provider.env`` is the only authoritative source for its node
ID.  This module deliberately has no dependency on the dashboard or relay so
all local consumers can use the same fail-closed rule without creating a
second identity service.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets


DEFAULT_PROVIDER_ENV = Path("/etc/computemesh/provider.env")
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class NodeIdentityError(RuntimeError):
    """Raised when the persisted node identity is absent or inconsistent."""


def is_nodeos_mode() -> bool:
    return os.environ.get("COMPUTEMESH_NODEOS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def provider_env_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("COMPUTEMESH_PROVIDER_ENV", "").strip()
    return Path(configured) if configured else DEFAULT_PROVIDER_ENV


_resolve_provider_env_path = provider_env_path


def validate_node_id(value: object) -> str:
    if not isinstance(value, str):
        raise NodeIdentityError("persisted provider identity has a non-text node id")
    candidate = value.strip()
    if not NODE_ID_PATTERN.fullmatch(candidate):
        raise NodeIdentityError("persisted provider identity contains an invalid node id")
    return candidate


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise NodeIdentityError("persisted provider identity cannot be read") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def read_enrolled_node_id(path: Path | str | None = None) -> str | None:
    """Return the enrolled node ID, or ``None`` only before enrollment.

    An existing but malformed provider environment is an integrity failure and
    never falls back to ``NODE_NAME`` or the hostname.
    """
    env_path = provider_env_path(path)
    if not env_path.exists():
        return None
    if env_path.is_symlink() or not env_path.is_file():
        raise NodeIdentityError("persisted provider identity path is not a regular file")

    values = _parse_env(env_path)
    raw_node_id = values.get("COMPUTEMESH_NODE_ID")
    if not raw_node_id:
        raise NodeIdentityError("persisted provider identity is missing COMPUTEMESH_NODE_ID")
    node_id = validate_node_id(raw_node_id)

    # The receipt is not needed for legacy installations, but when present it
    # is an independent local consistency check for an enrollment/migration.
    receipt_path = env_path.parent / "enrollment.receipt.json"
    if receipt_path.exists():
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise NodeIdentityError("enrollment receipt is not a regular file")
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise NodeIdentityError("enrollment receipt cannot be read") from exc
        if not isinstance(receipt, dict) or receipt.get("node_id") != node_id:
            raise NodeIdentityError("persisted provider identity and enrollment receipt disagree")
    return node_id


def resolve_node_id(
    explicit_node_id: str | None = None,
    *,
    fallback_node_id: str | None = None,
    require_enrolled: bool = False,
    provider_env_path: Path | str | None = None,
) -> str:
    """Resolve one node ID with persisted enrollment taking precedence."""
    persisted = read_enrolled_node_id(provider_env_path)
    explicit = explicit_node_id.strip() if isinstance(explicit_node_id, str) else ""
    if persisted is not None:
        if explicit and explicit != persisted:
            raise NodeIdentityError("explicit node id does not match persisted provider identity")
        return persisted
    if require_enrolled:
        raise NodeIdentityError("node is not enrolled; persisted provider identity is required")
    if explicit:
        return validate_node_id(explicit)
    if fallback_node_id:
        return validate_node_id(fallback_node_id)
    raise NodeIdentityError("no node identity is available")


def _atomic_text_write(path: Path, content: str, mode: int = 0o600) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise NodeIdentityError("refusing symlinked identity path")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{secrets.token_hex(8)}")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(mode)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except (OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise NodeIdentityError("cannot persist node identity migration") from exc


def migrate_enrolled_node_id(
    new_node_id: str,
    *,
    previous_node_id: str,
    provider_env_path: Path | str | None = None,
) -> Path:
    """Persist an explicitly authorized node-ID migration.

    Callers must prove the old ID in the same authenticated rename flow.  A
    normal boot or config save cannot silently change an enrolled identity.
    """
    resolved_path = _resolve_provider_env_path(provider_env_path)
    current = read_enrolled_node_id(resolved_path)
    if current is None:
        raise NodeIdentityError("cannot migrate an unenrolled node identity")
    previous = validate_node_id(previous_node_id)
    new_id = validate_node_id(new_node_id)
    if current != previous:
        raise NodeIdentityError("previous node id does not match persisted provider identity")
    if new_id == current:
        return resolved_path
    if str(resolved_path).startswith(("/boot", "/live", "/run/live")):
        raise NodeIdentityError("provider identity must remain on persistent storage")

    original_env = resolved_path.read_text(encoding="utf-8")
    updated_lines = []
    replaced = False
    for line in original_env.splitlines(keepends=True):
        if line.lstrip().startswith("COMPUTEMESH_NODE_ID="):
            ending = "\n" if line.endswith("\n") else ""
            updated_lines.append(f"COMPUTEMESH_NODE_ID={new_id}{ending}")
            replaced = True
        else:
            updated_lines.append(line)
    if not replaced:
        raise NodeIdentityError("provider environment lacks COMPUTEMESH_NODE_ID")

    receipt_path = resolved_path.parent / "enrollment.receipt.json"
    original_receipt: str | None = None
    updated_receipt: str | None = None
    if receipt_path.exists():
        original_receipt = receipt_path.read_text(encoding="utf-8")
        try:
            receipt = json.loads(original_receipt)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise NodeIdentityError("enrollment receipt cannot be migrated") from exc
        if not isinstance(receipt, dict) or receipt.get("node_id") != current:
            raise NodeIdentityError("enrollment receipt does not match current identity")
        receipt["node_id"] = new_id
        updated_receipt = json.dumps(receipt, sort_keys=True) + "\n"

    _atomic_text_write(resolved_path, "".join(updated_lines))
    try:
        if updated_receipt is not None:
            _atomic_text_write(receipt_path, updated_receipt)
    except NodeIdentityError:
        _atomic_text_write(resolved_path, original_env)
        if original_receipt is not None:
            _atomic_text_write(receipt_path, original_receipt)
        raise
    return resolved_path


def dashboard_must_not_start_relay() -> bool:
    """The dedicated NodeOS heartbeat unit owns the relay process."""
    return is_nodeos_mode()
