"""Live NodeOS images must embed a kernel/initramfs pair from one release."""

from pathlib import Path

import pytest
from deploy.appliance.build_real_live_appliance import _copy_matched_boot_pair


def _directories(tmp_path: Path) -> tuple[Path, Path]:
    boot = tmp_path / "chroot" / "boot"
    target = tmp_path / "iso" / "boot"
    boot.mkdir(parents=True)
    target.mkdir(parents=True)
    return boot, target


def test_absent_kernel_or_initramfs_fails_before_packaging(tmp_path: Path) -> None:
    boot, target = _directories(tmp_path)
    with pytest.raises(RuntimeError, match="matching nonempty kernel/initramfs"):
        _copy_matched_boot_pair(boot, target)
    (boot / "vmlinuz-6.12.0").write_bytes(b"kernel")
    with pytest.raises(RuntimeError, match="matching nonempty kernel/initramfs"):
        _copy_matched_boot_pair(boot, target)
    assert list(target.iterdir()) == []


def test_different_kernel_and_initramfs_versions_rejected(tmp_path: Path) -> None:
    boot, target = _directories(tmp_path)
    (boot / "vmlinuz-6.12.0").write_bytes(b"kernel")
    (boot / "initrd.img-6.11.0").write_bytes(b"wrong")
    with pytest.raises(RuntimeError, match="matching nonempty kernel/initramfs"):
        _copy_matched_boot_pair(boot, target)
    assert list(target.iterdir()) == []


def test_empty_initramfs_is_not_accepted(tmp_path: Path) -> None:
    boot, target = _directories(tmp_path)
    (boot / "vmlinuz-6.12.0").write_bytes(b"kernel")
    (boot / "initrd.img-6.12.0").write_bytes(b"")
    with pytest.raises(RuntimeError, match="matching nonempty kernel/initramfs"):
        _copy_matched_boot_pair(boot, target)


def test_only_complete_matching_pair_is_copied(tmp_path: Path) -> None:
    boot, target = _directories(tmp_path)
    (boot / "vmlinuz-6.12.0").write_bytes(b"kernel-new")
    (boot / "initrd.img-6.12.0").write_bytes(b"")
    (boot / "vmlinuz-6.11.0").write_bytes(b"kernel-old")
    (boot / "initrd.img-6.11.0").write_bytes(b"initrd-old")
    assert _copy_matched_boot_pair(boot, target) == "6.11.0"
    assert (target / "vmlinuz").read_bytes() == b"kernel-old"
    assert (target / "initrd.img").read_bytes() == b"initrd-old"


def test_symlinked_boot_files_rejected(tmp_path: Path) -> None:
    boot, target = _directories(tmp_path)
    original = tmp_path / "outside-kernel"
    original.write_bytes(b"kernel")
    (boot / "initrd.img-6.12.0").write_bytes(b"initrd")
    try:
        (boot / "vmlinuz-6.12.0").symlink_to(original)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unsupported: {exc}")
    with pytest.raises(RuntimeError, match="matching nonempty kernel/initramfs"):
        _copy_matched_boot_pair(boot, target)
    assert list(target.iterdir()) == []
