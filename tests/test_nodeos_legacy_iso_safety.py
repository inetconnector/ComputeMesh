"""Fail-closed NodeOS legacy ISO builder regression tests."""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from deploy.appliance.build_real_iso import (
    _copy_matched_boot_files,
    _set_download_permissions,
)


def test_missing_or_mismatched_boot_files_fail_closed(tmp_path: Path) -> None:
    boot = tmp_path / "boot"
    boot.mkdir()
    output = tmp_path / "iso"
    output.mkdir()
    with pytest.raises(RuntimeError, match="matching kernel and initramfs"):
        _copy_matched_boot_files(boot, output)
    (boot / "vmlinuz-6.1").write_bytes(b"kernel")
    (boot / "initrd.img-6.2").write_bytes(b"wrong version")
    with pytest.raises(RuntimeError, match="matching kernel and initramfs"):
        _copy_matched_boot_files(boot, output)
    (boot / "initrd.img-6.1").write_bytes(b"")
    with pytest.raises(RuntimeError, match="matching kernel and initramfs"):
        _copy_matched_boot_files(boot, output)
    assert not list(output.iterdir())


def test_matched_nonempty_boot_files_copied(tmp_path: Path) -> None:
    boot = tmp_path / "boot"
    boot.mkdir()
    output = tmp_path / "iso"
    output.mkdir()
    (boot / "vmlinuz-6.1").write_bytes(b"kernel")
    (boot / "initrd.img-6.1").write_bytes(b"initrd")
    _copy_matched_boot_files(boot, output)
    assert (output / "vmlinuz").read_bytes() == b"kernel"
    assert (output / "initrd.img").read_bytes() == b"initrd"


def test_release_permission_errors_abort(tmp_path: Path) -> None:
    failure = subprocess.CalledProcessError(1, ["chown"])
    with patch("deploy.appliance.build_real_iso.subprocess.run", side_effect=failure) as run, pytest.raises(
        subprocess.CalledProcessError
    ):
        _set_download_permissions(tmp_path / "iso", tmp_path / "xz")
    run.assert_called_once()
    assert run.call_args.kwargs["check"] is True


def test_release_permission_commands_are_checked(tmp_path: Path) -> None:
    iso = tmp_path / "iso"
    xz = tmp_path / "xz"
    with patch("deploy.appliance.build_real_iso.subprocess.run") as run:
        _set_download_permissions(iso, xz)
    assert run.call_count == 2
    assert all(c.kwargs["check"] is True for c in run.call_args_list)
    assert run.call_args_list[-1].args[0] == ["chmod", "644", str(iso), str(xz)]
