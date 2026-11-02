"""Private appliance configuration is never published world-readable."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.appliance import appliance_config as storage


def test_private_config_written_with_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / "private" / "owner.json"
    storage._write_private_json(path, {"owner_key": "ephemeral-test-only"})
    assert json.loads(path.read_text(encoding="utf-8"))["owner_key"] == "ephemeral-test-only"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode test")
def test_chmod_failure_preserves_previous_private_file(tmp_path: Path) -> None:
    path = tmp_path / "owner.json"
    path.write_text("existing", encoding="utf-8")
    with patch.object(storage.os, "chmod", side_effect=PermissionError("chmod unavailable")):
        with pytest.raises(PermissionError, match="chmod unavailable"):
            storage._write_private_json(path, {"owner_key": "must-not-publish"})
    assert path.read_text(encoding="utf-8") == "existing"
    assert not list(tmp_path.glob(".owner.json.*.tmp"))


def test_symlinked_config_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "actual"
    target.write_text("untouched", encoding="utf-8")
    link = tmp_path / "owner.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unsupported: {exc}")
    with pytest.raises(OSError, match="symlink"):
        storage._write_private_json(link, {"owner_key": "test"})
    assert target.read_text(encoding="utf-8") == "untouched"


def test_private_storage_error_cannot_be_hidden_by_save(tmp_path: Path) -> None:
    with patch.object(storage, "_write_private_json", side_effect=OSError("storage unavailable")):
        with pytest.raises(OSError, match="storage unavailable"):
            storage.save_system_config(storage.ApplianceConfig(owner_key="test"), tmp_path / "system.json")


def test_invalid_existing_provider_json_does_not_modify_system_config(tmp_path: Path) -> None:
    user_dir = tmp_path / ".computemesh"
    user_dir.mkdir()
    (user_dir / "provider_config.json").write_text("{invalid", encoding="utf-8")
    system_file = tmp_path / "system.json"
    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(json.JSONDecodeError):
            storage.save_system_config(storage.ApplianceConfig(owner_key="test"), system_file)
    assert not system_file.exists()
