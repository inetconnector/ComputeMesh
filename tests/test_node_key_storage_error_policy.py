"""Node-key loading never silently hides unexpected storage failures."""

from pathlib import Path
from unittest.mock import patch

import pytest
from tools.security import node_key_storage as storage


def test_malformed_base64_still_rejects_invalid_key(tmp_path: Path) -> None:
    key_file = tmp_path / "invalid.key"
    key_file.write_bytes(b"not-a-valid-private-key!!!")
    key_file.chmod(0o600)
    with pytest.raises(storage.KeyStorageError):
        storage.load_node_private_key(key_file)


def test_unexpected_decoder_error_propagates(tmp_path: Path) -> None:
    key_file = tmp_path / "unexpected-decoder.key"
    key_file.write_bytes(b"not-valid-base64-data-longer-than-32")
    key_file.chmod(0o600)
    with patch.object(storage.base64, "b64decode", side_effect=RuntimeError("decoder malfunction")), pytest.raises(RuntimeError, match="decoder malfunction"):
        storage.load_node_private_key(key_file)


def test_unexpected_root_path_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMPUTEMESH_NODE_KEY_PATH", raising=False)
    with (
        patch.object(storage.platform, "system", return_value="Linux"),
        patch.object(storage.os, "geteuid", return_value=0, create=True),
        patch.object(storage.os.path, "lexists", return_value=False),
        patch.object(storage.Path, "mkdir", side_effect=RuntimeError("broken path policy")),pytest.raises(RuntimeError, match="broken path policy")
    ):
        storage.get_or_create_node_private_key(allow_generate=True)


def test_unwritable_root_candidate_uses_existing_home_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COMPUTEMESH_NODE_KEY_PATH", raising=False)
    with (
        patch.object(storage.platform, "system", return_value="Linux"),
        patch.object(storage.os, "geteuid", return_value=0, create=True),
        patch.object(storage.os.path, "lexists", return_value=False),
        patch.object(storage.Path, "mkdir", side_effect=PermissionError("readonly root")),
        patch.object(storage.Path, "home", return_value=tmp_path),
        patch.object(storage, "save_node_private_key") as save,
    ):
        _key, path = storage.get_or_create_node_private_key(allow_generate=True)
    assert path == tmp_path / ".computemesh" / "node_identity.key"
    save.assert_called_once()
    assert save.call_args.args[1] == path
