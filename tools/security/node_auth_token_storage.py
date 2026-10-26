"""Side-effect-free persistent storage for the enrollment-issued node token.

This module deliberately does not import the dashboard relay and never creates a
token at import time.  Enrollment imports only the persistence primitive after
the gateway has accepted the signed request; the relay may use the generation
helper for its legacy non-NodeOS desktop mode through a compatibility wrapper.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
import os
from pathlib import Path
import secrets
import sys


TOKEN_PREFIX = "cm_tunnel_"
_LIVE_PATH_PREFIXES = ("/boot", "/live", "/run/live")


class NodeAuthTokenStorageError(RuntimeError):
    """Raised when a node token cannot be read or durably persisted."""


def nodeos_mode() -> bool:
    return os.environ.get("COMPUTEMESH_NODEOS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def default_node_auth_paths() -> list[Path]:
    configured = os.environ.get("COMPUTEMESH_NODE_AUTH_TOKEN_PATH", "").strip()
    paths = [Path(configured)] if configured else []
    paths.extend(
        (
            Path("/var/lib/computemesh/node_auth_token.txt"),
            Path.home() / ".computemesh" / "node_auth_token.txt",
            Path("/etc/computemesh/node_auth_token.txt"),
        )
    )
    return paths


def validate_node_auth_token(token: str) -> str:
    value = str(token).strip()
    if not value.startswith(TOKEN_PREFIX) or not value[len(TOKEN_PREFIX) :].isalnum():
        raise NodeAuthTokenStorageError("node authentication token has an invalid format")
    return value


def read_existing_node_auth_token(search_paths: Iterable[Path] | None = None) -> str | None:
    for raw_path in search_paths or default_node_auth_paths():
        path = Path(raw_path)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise NodeAuthTokenStorageError(f"node token path is not a regular file: {path}")
        if not path.exists():
            continue
        try:
            token = validate_node_auth_token(path.read_text(encoding="utf-8"))
        except NodeAuthTokenStorageError:
            raise
        except Exception as exc:  # pragma: no cover - platform-specific I/O
            raise NodeAuthTokenStorageError(f"cannot read persistent node token: {path}") from exc
        return token
    return None


def atomic_secure_text_write(path: Path, value: str) -> None:
    """Durably replace one token file without following symlinks."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise NodeAuthTokenStorageError(f"refusing symlinked node token path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        path.parent.chmod(0o700)

    temp_path = path.with_name(f"{path.name}.tmp.{secrets.token_hex(8)}")
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if sys.platform != "win32":
            os.chmod(path, 0o600)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except NodeAuthTokenStorageError:
        raise
    except Exception as exc:  # pragma: no cover - platform-specific I/O
        raise NodeAuthTokenStorageError(f"cannot durably persist node token: {path}") from exc
    finally:
        temp_path.unlink(missing_ok=True)


def get_or_create_node_auth_token(
    search_paths: Iterable[Path] | None = None,
    *,
    atomic_writer: Callable[[Path, str], None] | None = None,
) -> str:
    """Read an existing token or create one only for non-NodeOS callers."""
    candidate_paths = [Path(path) for path in (search_paths or default_node_auth_paths())]
    existing = read_existing_node_auth_token(candidate_paths)
    if existing is not None:
        return existing
    if nodeos_mode():
        raise NodeAuthTokenStorageError(
            "persistent node token is missing on NodeOS; refusing to generate a new identity"
        )

    new_token = TOKEN_PREFIX + secrets.token_hex(24)
    writer = atomic_writer or atomic_secure_text_write
    last_error: Exception | None = None
    for target in candidate_paths:
        try:
            writer(Path(target), new_token)
            return new_token
        except Exception as exc:  # noqa: BLE001 - try the next authorized tier
            last_error = exc
    raise NodeAuthTokenStorageError("cannot persist node authentication token") from last_error


def persist_node_auth_token(
    token: str,
    path: Path | None = None,
    *,
    atomic_writer: Callable[[Path, str], None] | None = None,
) -> Path:
    """Persist the gateway-issued token, accepting only an identical retry."""
    value = validate_node_auth_token(token)
    target = Path(path) if path is not None else default_node_auth_paths()[0]
    if str(target).startswith(_LIVE_PATH_PREFIXES):
        raise NodeAuthTokenStorageError("node authentication token must be stored on persistent storage")
    existing = read_existing_node_auth_token([target])
    if existing is not None:
        if existing != value:
            raise NodeAuthTokenStorageError("persistent node authentication token would be replaced")
        return target
    (atomic_writer or atomic_secure_text_write)(target, value)
    return target
