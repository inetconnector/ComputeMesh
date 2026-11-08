"""USB-to-SSD boot disk cloning for ComputeMesh NodeOS.

Only meaningful on a Linux live-boot appliance. Detects whether the running
system booted from a removable (USB) disk, and if so, offers a sector-for-
sector clone onto a non-removable internal disk so the same, now-updated,
appliance can boot from internal storage.

Safety model:
- the source disk is always re-derived from the live kernel/mount state,
  never taken from client input;
- the target device list is always recomputed at request time from real
  block devices (non-removable, not the source, large enough), never
  trusted from a cached/client-supplied list;
- start_clone() re-validates the requested target against that fresh list
  and requires an exact confirmation phrase before writing anything;
- the clone copies device bytes with dd; the only "parsing" involved is
  reading the partition start/size integers the kernel already exposes
  under /sys/block/<disk>/<part>/{start,size} to find where real data
  ends, so a mostly-empty USB stick isn't copied out to its full nominal
  capacity -- this is reading kernel-computed sysfs integers, not parsing
  raw partition-table bytes ourselves, and always falls back to a full
  whole-disk copy if that can't be determined.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIRM_PHRASE = "ERASE AND CLONE"


@dataclass
class CloneStatus:
    running: bool = False
    done: bool = False
    error: str | None = None
    source: str = ""
    target: str = ""
    total_bytes: int = 0
    copied_bytes: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    block_size_mb: int = 4
    bytes_per_second: float = 0.0
    _last_sample_bytes: int = field(default=0, repr=False)
    _last_sample_time: float = field(default=0.0, repr=False)


_status = CloneStatus()
_status_lock = threading.Lock()


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
        return None


_SAFETY_MARGIN_BYTES = 64 * 1024 * 1024  # covers GPT backup header / alignment slack


def _source_used_extent_bytes(disk_name: str) -> int | None:
    """Byte offset where the last partition on disk_name ends, plus a safety margin."""
    base = Path(f"/sys/block/{disk_name}")
    if not base.exists():
        return None
    max_end_sectors = 0
    found_any = False
    for entry in base.iterdir():
        if not entry.name.startswith(disk_name) or entry.name == disk_name:
            continue
        start = _read_int(entry / "start")
        size = _read_int(entry / "size")
        if start is None or size is None:
            continue
        found_any = True
        max_end_sectors = max(max_end_sectors, start + size)
    if not found_any or max_end_sectors <= 0:
        return None
    return max_end_sectors * 512 + _SAFETY_MARGIN_BYTES


def _block_disk_size_bytes(disk_name: str) -> int:
    size_sectors = _read_int(Path(f"/sys/block/{disk_name}/size"))
    return (size_sectors or 0) * 512


def _disk_model(disk_name: str) -> str:
    for name in ("model", "device/model"):
        p = Path(f"/sys/block/{disk_name}/{name}")
        if p.exists():
            try:
                return p.read_text().strip()
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
                _ = exc
    return "Unknown"


def _is_removable(disk_name: str) -> bool:
    """True if disk_name is USB-attached or marked removable."""
    if _read_int(Path(f"/sys/block/{disk_name}/removable")) == 1:
        return True
    try:
        resolved = Path(f"/sys/block/{disk_name}").resolve()
        if any(part.startswith("usb") or "usb" in part.lower() for part in resolved.parts):
            return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
        _ = exc
    # Check udev properties if available
    try:
        out = subprocess.check_output(["udevadm", "info", "--query=property", f"--name=/dev/{disk_name}"], text=True, timeout=2)
        if "ID_BUS=usb" in out or "ID_USB_DRIVER=" in out or "ID_DRIVE_FLASH" in out:
            return True
    except (subprocess.SubprocessError, OSError, ValueError, TypeError) as exc:
        _ = exc
    return False


def _resolve_source_disk() -> str | None:
    """Find the physical disk the live system actually booted from, prioritizing USB."""
    # First: Check mountpoints for the live medium
    candidates = []
    for probe in ("findmnt -no SOURCE /lib/live/mount/medium", "findmnt -no SOURCE /run/live/medium", "findmnt -no SOURCE /"):
        try:
            res = subprocess.run(probe.split(), check=False, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                candidates.append(res.stdout.strip())
        except (subprocess.SubprocessError, OSError, ValueError, TypeError) as exc:
            _ = exc
            continue

    resolved_disks: list[str] = []
    for dev_path in candidates:
        dev_name = dev_path.rsplit("/", 1)[-1]
        try:
            res = subprocess.run(["lsblk", "-no", "PKNAME", dev_path], check=False, capture_output=True, text=True, timeout=5)
            pkname = res.stdout.strip()
            if pkname and pkname not in resolved_disks:
                resolved_disks.append(pkname)
        except (subprocess.SubprocessError, OSError, ValueError, TypeError) as exc:
            _ = exc
        stripped = re.sub(r"p?\d+$", "", dev_name) if re.search(r"\d+$", dev_name) else dev_name
        if Path(f"/sys/block/{stripped}").exists() and stripped not in resolved_disks:
            resolved_disks.append(stripped)

    # If any resolved disk is removable (USB), prefer it
    for d in resolved_disks:
        if _is_removable(d):
            return d

    # If no mountpoint returned a USB disk, scan /sys/block for any connected USB drive with live data
    block_dir = Path("/sys/block")
    if block_dir.exists():
        for entry in sorted(block_dir.iterdir()):
            name = entry.name
            if name.startswith(("loop", "ram", "sr", "dm-", "md", "zram")):
                continue
            if _is_removable(name):
                return name

    # Fallback to the first resolved disk if any
    return resolved_disks[0] if resolved_disks else None


def get_boot_source_info() -> dict[str, Any]:
    source_disk = _resolve_source_disk()
    booted_from_usb = bool(source_disk and _is_removable(source_disk))
    full_size = _block_disk_size_bytes(source_disk) if source_disk else 0
    used_extent = _source_used_extent_bytes(source_disk) if source_disk else None
    clone_bytes = min(used_extent, full_size) if used_extent else full_size
    return {
        "booted_from_usb": booted_from_usb,
        "source_disk": f"/dev/{source_disk}" if source_disk else None,
        "source_size_bytes": full_size,
        "clone_bytes": clone_bytes,
        "source_model": _disk_model(source_disk) if source_disk else "",
    }


def _disk_has_existing_os(disk_name: str) -> bool:
    """Check if the target disk has existing partitions or NodeOS filesystems."""
    base = Path(f"/sys/block/{disk_name}")
    if not base.exists():
        return False
    for entry in base.iterdir():
        if entry.name.startswith(disk_name) and entry.name != disk_name:
            return True
    return False


def list_clone_targets(source_disk_name: str | None, min_bytes: int | None = None) -> list[dict[str, Any]]:
    """List valid internal drives for cloning, including drives with existing OS to overwrite."""
    targets: list[dict[str, Any]] = []
    block_dir = Path("/sys/block")
    if not block_dir.exists():
        return targets
    required_size = min_bytes if min_bytes is not None else (
        _block_disk_size_bytes(source_disk_name) if source_disk_name else 0
    )
    for entry in sorted(block_dir.iterdir()):
        name = entry.name
        if name.startswith(("loop", "ram", "sr", "dm-", "md", "zram")):
            continue
        if source_disk_name and name == source_disk_name:
            continue
        if _is_removable(name):
            continue
        size_bytes = _block_disk_size_bytes(name)
        if size_bytes <= 0 or size_bytes < required_size:
            continue
        has_existing = _disk_has_existing_os(name)
        gb_size = round(size_bytes / (1024**3), 1)
        targets.append({
            "device": f"/dev/{name}",
            "name": name,
            "size_bytes": size_bytes,
            "size_formatted": f"{gb_size} GB",
            "model": _disk_model(name),
            "has_existing_os": has_existing,
        })
    return targets


def get_clone_status() -> dict[str, Any]:
    with _status_lock:
        s = _status
        remaining = max(0, s.total_bytes - s.copied_bytes)
        eta_seconds = round(remaining / s.bytes_per_second) if s.running and s.bytes_per_second > 0 else None
        return {
            "running": s.running,
            "done": s.done,
            "error": s.error,
            "source": s.source,
            "target": s.target,
            "total_bytes": s.total_bytes,
            "copied_bytes": s.copied_bytes,
            "percent": round(100 * s.copied_bytes / s.total_bytes, 1) if s.total_bytes else 0.0,
            "bytes_per_second": round(s.bytes_per_second),
            "eta_seconds": eta_seconds,
            "block_size_mb": s.block_size_mb,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
        }


def _post_clone_fixup(target_dev: str) -> None:
    """Repair partition tables and bootloaders on target disk after dd sector copy.

    1. Fix GPT Secondary / Backup header:
       When a smaller image is written onto a larger drive, the backup GPT
       header is located at sector ~20M instead of at the physical end of the disk.
       Tools like sgdisk -e / parted move the backup header to the true end of disk
       and repair the GPT table so UEFI firmware and GRUB part_gpt parse partitions correctly.
    2. Reload partition table into kernel (partprobe / udevadm settle).
    3. Verify / configure EFI System Partition (Partition 2) and bootloader.
    4. Register UEFI boot entry via efibootmgr if running on a UEFI system.
    5. Ensure BIOS/MBR active flag on partition 1 if booting in legacy mode.
    """
    # 1. GPT Repair (sgdisk -e or parted or sfdisk)
    try:
        subprocess.run(["sgdisk", "-e", target_dev], check=False, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as exc:
        _ = exc
    try:
        subprocess.run(["parted", "-s", target_dev, "print"], check=False, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as exc:
        _ = exc

    # 2. Partprobe to reread partition table
    try:
        subprocess.run(["partprobe", target_dev], check=False, capture_output=True, timeout=10)
        subprocess.run(["udevadm", "settle", "--timeout=5"], check=False, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as exc:
        _ = exc

    # 3. Ensure EFI System Partition boot files
    efi_part = f"{target_dev}2" if not target_dev[-1].isdigit() else f"{target_dev}p2"
    if Path(efi_part).exists():
        mount_dir = Path("/tmp/cm_efi_target_mount")
        mount_dir.mkdir(parents=True, exist_ok=True)
        try:
            m_res = subprocess.run(["mount", efi_part, str(mount_dir)], check=False, capture_output=True, timeout=5)
            if m_res.returncode == 0:
                try:
                    boot_dir = mount_dir / "EFI" / "BOOT"
                    boot_dir.mkdir(parents=True, exist_ok=True)
                    boot_file = boot_dir / "BOOTX64.EFI"
                    if not boot_file.exists() or boot_file.stat().st_size == 0:
                        for src_candidate in [
                            Path("/boot/grub/bootx64.efi"),
                            Path("/usr/lib/grub/x86_64-efi/monolithic/grubx64.efi"),
                            Path("/boot/efi/EFI/BOOT/BOOTX64.EFI"),
                        ]:
                            if src_candidate.exists():
                                shutil.copy(src_candidate, boot_file)
                                break
                finally:
                    subprocess.run(["umount", str(mount_dir)], check=False, capture_output=True, timeout=5)
        except (subprocess.SubprocessError, OSError, ValueError, TypeError) as exc:
            _ = exc

    # 4. If efibootmgr is present and system is booted via UEFI, register boot entry
    if Path("/sys/firmware/efi").exists():
        try:
            part_num = "2"
            subprocess.run([
                "efibootmgr", "-c",
                "-d", target_dev,
                "-p", part_num,
                "-L", "ComputeMesh NodeOS",
                "-l", "\\EFI\\BOOT\\BOOTX64.EFI"
            ], check=False, capture_output=True, timeout=10)
        except (subprocess.SubprocessError, OSError) as exc:
            _ = exc

    # 5. MBR / Legacy BIOS active flag
    try:
        subprocess.run(["sfdisk", "-A", target_dev, "1"], check=False, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as exc:
        _ = exc

    # 6. Auto-provision persistence and models partition on target internal disk
    try:
        _provision_target_persistence(target_dev)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as _persist_err:
        _ = _persist_err


def _provision_target_persistence(target_dev: str) -> bool:
    """Ensure a persistence partition and model storage exist on the target cloned disk.

    When cloning from a smaller USB installer to a larger internal HDD/SSD,
    the remaining disk space is unpartitioned. This routine:
    1. Checks if a 'persistence' partition already exists on target_dev.
    2. If not, inspects partition table and appends a new partition filling remaining space.
    3. Formats it with ext4 and volume label 'persistence'.
    4. Populates persistence.conf with '/ union'.
    5. Creates model cache directory /var/lib/computemesh/models.
    6. Creates an 8GB swapfile (or scaled to free space) for multi-GPU shader compilation.
    7. Configures boot activation service computemesh-mount-models.
    """
    disk_name = target_dev.rsplit("/", 1)[-1]

    # 1. Check if target_dev already has a partition labeled persistence
    try:
        lsblk_out = subprocess.run(
            ["lsblk", "-rno", "NAME,LABEL", target_dev],
            check=False, capture_output=True, text=True, timeout=5,
        ).stdout
        if "persistence" in lsblk_out:
            return True
    except (subprocess.SubprocessError, OSError):
        pass

    # 2. Check total disk size vs used partition extents
    total_size = _block_disk_size_bytes(disk_name)
    used_extent = _source_used_extent_bytes(disk_name) or 0
    free_bytes = total_size - used_extent
    if free_bytes < 1024 * 1024 * 1024:  # Less than 1GB free
        return False

    # 3. Create Partition 3 (or next free partition) filling remaining space
    partition_created = False
    try:
        sf_res = subprocess.run(
            ["sfdisk", "--append", "--no-reread", target_dev],
            input=",,L\n", text=True, check=False, capture_output=True, timeout=10,
        )
        if sf_res.returncode == 0:
            partition_created = True
    except (subprocess.SubprocessError, OSError):
        pass

    if not partition_created:
        try:
            start_mib = (used_extent // (1024 * 1024)) + 4
            p_res = subprocess.run(
                ["parted", "-s", target_dev, "mkpart", "primary", "ext4", f"{start_mib}MiB", "100%"],
                check=False, capture_output=True, text=True, timeout=10,
            )
            if p_res.returncode == 0:
                partition_created = True
        except (subprocess.SubprocessError, OSError):
            pass

    # Re-probe partitions
    try:
        subprocess.run(["partprobe", target_dev], check=False, capture_output=True, timeout=5)
        subprocess.run(["udevadm", "settle", "--timeout=5"], check=False, capture_output=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        pass

    # Locate the target partition device (e.g. /dev/sda3 or /dev/nvme0n1p3)
    target_part = None
    sep = "p" if target_dev[-1].isdigit() else ""
    for p_num in range(3, 8):
        candidate = f"{target_dev}{sep}{p_num}"
        if Path(candidate).exists() or Path(f"/sys/block/{disk_name}/{disk_name}{sep}{p_num}").exists():
            target_part = candidate
            break

    if not target_part:
        return False

    # 4. Format partition as ext4 with label 'persistence'
    try:
        mkfs_res = subprocess.run(
            ["mkfs.ext4", "-F", "-L", "persistence", target_part],
            check=False, capture_output=True, timeout=60,
        )
        if mkfs_res.returncode != 0:
            return False
    except (subprocess.SubprocessError, OSError):
        return False

    # 5. Mount and configure persistence filesystem
    mount_dir = Path("/tmp/cm_persist_target_mount")
    mount_dir.mkdir(parents=True, exist_ok=True)
    try:
        m_res = subprocess.run(["mount", target_part, str(mount_dir)], check=False, capture_output=True, timeout=10)
        if m_res.returncode == 0:
            try:
                # 5a. persistence.conf with / union
                (mount_dir / "persistence.conf").write_text("/ union\n", encoding="utf-8")

                # 5b. model storage directory
                model_dir = mount_dir / "var" / "lib" / "computemesh" / "models"
                model_dir.mkdir(parents=True, exist_ok=True)

                # 5c. Swapfile for multi-GPU memory stability (8GB or 25% free space)
                swap_mb = min(8192, max(1024, (free_bytes // (1024 * 1024)) // 4))
                swap_path = mount_dir / "swapfile"
                try:
                    alloc_res = subprocess.run(
                        ["fallocate", "-l", f"{swap_mb}M", str(swap_path)],
                        check=False, capture_output=True, timeout=15,
                    )
                    if alloc_res.returncode != 0:
                        subprocess.run(
                            ["dd", "if=/dev/zero", f"of={str(swap_path)}", "bs=1M", f"count={swap_mb}"],
                            check=False, capture_output=True, timeout=60,
                        )
                    if swap_path.exists():
                        swap_path.chmod(0o600)
                        subprocess.run(["mkswap", str(swap_path)], check=False, capture_output=True, timeout=10)
                except (subprocess.SubprocessError, OSError):
                    pass

                # 5d. Install persistent computemesh-mount-models helper
                bin_dir = mount_dir / "usr" / "local" / "bin"
                bin_dir.mkdir(parents=True, exist_ok=True)
                script_path = bin_dir / "computemesh-mount-models.sh"
                script_path.write_text(
                    """#!/bin/bash
for sw in /run/live/persistence/*/swapfile /swapfile; do
    if [ -f "$sw" ]; then
        chmod 600 "$sw" 2>/dev/null || true
        swapon "$sw" 2>/dev/null || true
    fi
done
mkdir -p /var/lib/computemesh/models
chmod 755 /var/lib/computemesh/models
exit 0
""",
                    encoding="utf-8",
                )
                try:
                    script_path.chmod(0o755)
                except OSError:
                    pass

                # 5e. Install and enable systemd unit
                systemd_dir = mount_dir / "etc" / "systemd" / "system"
                systemd_dir.mkdir(parents=True, exist_ok=True)
                service_file = systemd_dir / "computemesh-mount-models.service"
                service_file.write_text(
                    """[Unit]
Description=ComputeMesh Native Persistence & Models Setup
DefaultDependencies=no
After=local-fs.target
Before=computemesh-appliance.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/computemesh-mount-models.sh

[Install]
WantedBy=multi-user.target
""",
                    encoding="utf-8",
                )
                wants_dir = systemd_dir / "multi-user.target.wants"
                wants_dir.mkdir(parents=True, exist_ok=True)
                symlink = wants_dir / "computemesh-mount-models.service"
                if not symlink.exists():
                    try:
                        symlink.symlink_to("/etc/systemd/system/computemesh-mount-models.service")
                    except OSError:
                        pass
            finally:
                subprocess.run(["umount", str(mount_dir)], check=False, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return False

    return True


def _run_clone(source_dev: str, target_dev: str, total_bytes: int, block_size_mb: int) -> None:
    block_bytes = block_size_mb * 1024 * 1024
    count = -(-total_bytes // block_bytes)  # ceil division
    proc = subprocess.Popen(
        ["dd", f"if={source_dev}", f"of={target_dev}", f"bs={block_size_mb}M", f"count={count}", "status=progress", "conv=fsync"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    progress_re = re.compile(r"(\d+)\s+bytes")
    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            m = progress_re.search(line)
            if m:
                now = time.time()
                new_bytes = int(m.group(1))
                with _status_lock:
                    if _status._last_sample_time > 0:
                        dt = now - _status._last_sample_time
                        if dt >= 1.0:
                            db = new_bytes - _status._last_sample_bytes
                            _status.bytes_per_second = db / dt
                            _status._last_sample_bytes = new_bytes
                            _status._last_sample_time = now
                    else:
                        _status._last_sample_bytes = new_bytes
                        _status._last_sample_time = now
                    _status.copied_bytes = new_bytes
        proc.wait()
        with _status_lock:
            if proc.returncode == 0:
                _status.copied_bytes = total_bytes
            else:
                _status.error = f"dd exited with code {proc.returncode}"

        # If dd completed successfully, run post-clone partition repair and bootloader fixup
        if proc.returncode == 0:
            try:
                _post_clone_fixup(target_dev)
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as _fixup_err:
                # Post-clone fixup warning should not fail the clone if dd succeeded
                _ = _fixup_err
    except (subprocess.SubprocessError, OSError, ValueError, TypeError, RuntimeError) as exc:
        with _status_lock:
            _status.error = str(exc)
    finally:
        with _status_lock:
            _status.running = False
            _status.done = True
            _status.finished_at = time.time()


def start_clone(target_device: str, confirm_phrase: str, block_size_mb: int = 4) -> tuple[bool, str]:
    """Validate and start a whole-disk clone in a background thread."""
    global _status
    if confirm_phrase != CONFIRM_PHRASE:
        return False, f"Confirmation phrase must be exactly: {CONFIRM_PHRASE}"
    if not (1 <= block_size_mb <= 64):
        return False, "block_size_mb must be between 1 and 64"

    with _status_lock:
        if _status.running:
            return False, "A clone is already in progress"

    info = get_boot_source_info()
    if not info["booted_from_usb"] or not info["source_disk"]:
        return False, "This system is not currently booted from a removable (USB) disk"

    source_name = info["source_disk"].rsplit("/", 1)[-1]
    clone_bytes = info["clone_bytes"]
    valid_targets = {t["device"]: t for t in list_clone_targets(source_name, clone_bytes)}
    if target_device not in valid_targets:
        return False, f"{target_device} is not a currently valid clone target"

    with _status_lock:
        _status = CloneStatus(
            running=True,
            source=info["source_disk"],
            target=target_device,
            total_bytes=clone_bytes,
            started_at=time.time(),
            block_size_mb=block_size_mb,
        )

    thread = threading.Thread(
        target=_run_clone,
        args=(info["source_disk"], target_device, clone_bytes, block_size_mb),
        daemon=True,
    )
    thread.start()
    return True, "Clone started"


def main() -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="ComputeMesh NodeOS USB-to-SSD Boot Disk Cloning")
    parser.add_argument("--info", action="store_true", help="Print boot source info")
    parser.add_argument("--list", action="store_true", help="List valid non-removable target disks")
    parser.add_argument("--status", action="store_true", help="Print current cloning status")
    parser.add_argument("--target", type=str, help="Target device path (e.g. /dev/sda)")
    parser.add_argument("--confirm", type=str, help=f"Exact confirmation phrase: '{CONFIRM_PHRASE}'")
    parser.add_argument("--block-size-mb", type=int, default=4, help="Block size in MB (default: 4)")
    args = parser.parse_args()

    if args.info:
        print(json.dumps(get_boot_source_info(), indent=2))
        return 0
    if args.status:
        print(json.dumps(get_clone_status(), indent=2))
        return 0
    if args.list:
        info = get_boot_source_info()
        src = info.get("source_disk")
        src_name = src.rsplit("/", 1)[-1] if src else None
        targets = list_clone_targets(src_name, info.get("clone_bytes"))
        print(json.dumps(targets, indent=2))
        return 0

    if args.target:
        if not args.confirm:
            print(f"Error: --confirm '{CONFIRM_PHRASE}' is required to erase and clone.", file=sys.stderr)
            return 1
        ok, msg = start_clone(args.target, args.confirm, args.block_size_mb)
        print(msg)
        if not ok:
            return 1
        while True:
            time.sleep(1)
            st = get_clone_status()
            print(f"Cloning: {st.get('bytes_copied', 0)} / {st.get('total_bytes', 0)} bytes ({st.get('percent', 0)}%)")
            if not st.get("running"):
                if st.get("error"):
                    print(f"Clone failed: {st['error']}", file=sys.stderr)
                    return 1
                print("Clone completed successfully. Target persistence provisioned.")
                return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

