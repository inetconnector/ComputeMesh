"""NodeOS build cleanup must never recurse through still-mounted host filesystems."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from deploy.appliance import build_real_live_appliance as builder


def test_mountinfo_parser_decodes_and_limits_to_build_root(tmp_path: Path) -> None:
    root = tmp_path / "nodeos"
    inside = root / "chroot" / "dev"
    escaped = str(inside).replace(" ", r"\040")
    source = (
        "10 1 0:1 / / rw - rootfs rootfs rw\n"
        f"11 10 0:2 / {escaped} rw - tmpfs tmpfs rw\n"
        f"12 11 0:3 / {escaped}/pts rw - devpts devpts rw\n"
    )
    with patch.object(builder.Path, "read_text", return_value=source):
        assert builder._mount_points_below(root) == [inside / "pts", inside]


def test_unknown_nested_mount_aborts_before_any_unmount(tmp_path: Path) -> None:
    root = tmp_path / "build"
    with (
        patch.object(builder, "BUILD_DIR", root),
        patch.object(builder, "CHROOT_DIR", root / "chroot"),
        patch.object(builder, "_mount_points_below", return_value=[root / "unknown"]),
        patch.object(builder.subprocess, "run") as run,
    ):
        with pytest.raises(RuntimeError, match="unrecognized"):
            builder._unmount_build_filesystems()
        run.assert_not_called()


def test_unmounts_nested_mounts_before_parent(tmp_path: Path) -> None:
    root = tmp_path / "build"
    dev = root / "chroot" / "dev"
    pts = dev / "pts"
    with (
        patch.object(builder, "BUILD_DIR", root),
        patch.object(builder, "CHROOT_DIR", root / "chroot"),
        patch.object(builder, "_mount_points_below", side_effect=[[pts, dev], []]),
        patch.object(builder.subprocess, "run") as run,
    ):
        builder._unmount_build_filesystems()
    assert [call.args[0] for call in run.call_args_list] == [
        ["umount", str(pts)], ["umount", str(dev)],
    ]
    assert all(call.kwargs.get("check") is True for call in run.call_args_list)


def test_failed_unmount_aborts_and_cannot_delete_tree(tmp_path: Path) -> None:
    root = tmp_path / "build"
    root.mkdir()
    marker = root / "must-stay"
    marker.write_text("keep", encoding="utf-8")
    dev = root / "chroot" / "dev"
    with (
        patch.object(builder, "BUILD_DIR", root),
        patch.object(builder, "CHROOT_DIR", root / "chroot"),
        patch.object(builder, "_mount_points_below", return_value=[dev]),
        patch.object(
            builder.subprocess, "run",
            side_effect=subprocess.CalledProcessError(32, ["umount"]),
        ),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            builder._cleanup_stale_build_tree()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_still_mounted_after_umount_refuses_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "build"
    root.mkdir()
    (root / "marker").write_text("keep", encoding="utf-8")
    proc = root / "chroot" / "proc"
    with (
        patch.object(builder, "BUILD_DIR", root),
        patch.object(builder, "CHROOT_DIR", root / "chroot"),
        patch.object(builder, "_mount_points_below", side_effect=[[proc], [proc]]),
        patch.object(builder.subprocess, "run") as run,
    ):
        with pytest.raises(RuntimeError, match="remain"):
            builder._cleanup_stale_build_tree()
    assert (root / "marker").exists()
    run.assert_called_once()


def test_symlinked_build_directory_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "marker").write_text("keep", encoding="utf-8")
    link = tmp_path / "build"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unsupported: {exc}")
    with patch.object(builder, "BUILD_DIR", link):
        with pytest.raises(RuntimeError, match="symlink"):
            builder._cleanup_stale_build_tree()
    assert (real / "marker").exists()


def test_malformed_mount_table_fails_closed(tmp_path: Path) -> None:
    with patch.object(builder.Path, "read_text", return_value="unexpected\n"):
        with pytest.raises(RuntimeError, match="malformed"):
            builder._mount_points_below(tmp_path)


def test_unreadable_mount_table_fails_closed(tmp_path: Path) -> None:
    with patch.object(builder.Path, "read_text", side_effect=OSError("permission")):
        with pytest.raises(RuntimeError, match="cannot inspect"):
            builder._mount_points_below(tmp_path)
