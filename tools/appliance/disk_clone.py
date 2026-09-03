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

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
import threading
import time
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
    # Rolling short-window rate, not a lifetime average: a lifetime average
    # reacts too slowly to actually diagnose a slow device/bridge while the
    # clone is running (which is the whole point of exposing this).
    bytes_per_second: float = 0.0
    _last_sample_bytes: int = field(default=0, repr=False)
    _last_sample_time: float = field(default=0.0, repr=False)


_status = CloneStatus()
_status_lock = threading.Lock()


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


_SAFETY_MARGIN_BYTES = 64 * 1024 * 1024  # covers GPT backup header / alignment slack


def _source_used_extent_bytes(disk_name: str) -> int | None:
    """Byte offset where the last partition on disk_name ends, plus a safety
    margin -- not the disk's full nominal capacity.

    A USB stick Etcher wrote a ~500MB image onto is often 8-300GB; only the
    space actually covered by a partition holds real data, the rest was
    never written by Etcher at all. Cloning past the last partition's end
    just copies untouched, meaningless bytes for hours. Returns None (caller
    falls back to the full disk size) if no partitions are found or sysfs
    can't be read, rather than risk guessing an extent that's too small.
    """
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
            except Exception:
                pass
    return "Unknown"


def _is_removable(disk_name: str) -> bool:
    """True if disk_name is USB-attached.

    The /sys/block/<dev>/removable flag alone is unreliable: many USB-SATA
    and USB-NVMe bridge chips report removable=0 for an externally-attached
    disk (observed live: a USB boot drive showed removable=0, model
    "External"). Resolving the device's real sysfs path and checking for a
    "usb" path component is what actually reflects the physical bus, and
    catches USB disks the removable flag misses.
    """
    if _read_int(Path(f"/sys/block/{disk_name}/removable")) == 1:
        return True
    try:
        resolved = Path(f"/sys/block/{disk_name}").resolve()
        return any(part.startswith("usb") for part in resolved.parts)
    except Exception:
        return False


def _resolve_source_disk() -> str | None:
    """Best-effort: find the physical disk the live system actually booted from."""
    candidates = []
    for probe in ("findmnt -no SOURCE /lib/live/mount/medium", "findmnt -no SOURCE /run/live/medium", "findmnt -no SOURCE /"):
        try:
            res = subprocess.run(probe.split(), capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                candidates.append(res.stdout.strip())
        except Exception:
            continue
    for dev_path in candidates:
        dev_name = dev_path.rsplit("/", 1)[-1]
        try:
            res = subprocess.run(["lsblk", "-no", "PKNAME", dev_path], capture_output=True, text=True, timeout=5)
            pkname = res.stdout.strip()
            if pkname:
                return pkname
        except Exception:
            pass
        # dev_name already looks like a whole disk (no trailing partition digits)
        stripped = re.sub(r"p?\d+$", "", dev_name) if re.search(r"\d+$", dev_name) else dev_name
        if Path(f"/sys/block/{stripped}").exists():
            return stripped
    return None


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
        # What actually needs to be copied (last partition's end + a safety
        # margin), which is what target-size filtering and the dd count=
        # should use -- not the source's full nominal capacity.
        "clone_bytes": clone_bytes,
        "source_model": _disk_model(source_disk) if source_disk else "",
    }


def list_clone_targets(source_disk_name: str | None, min_bytes: int | None = None) -> list[dict[str, Any]]:
    """min_bytes: required target size. Defaults to the source's full nominal
    size for backward compatibility, but callers should normally pass
    get_boot_source_info()["clone_bytes"] so a target only needs to fit the
    data actually being copied, not the source device's full capacity."""
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
        targets.append({
            "device": f"/dev/{name}",
            "name": name,
            "size_bytes": size_bytes,
            "model": _disk_model(name),
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


def _run_clone(source_dev: str, target_dev: str, total_bytes: int, block_size_mb: int) -> None:
    global _status
    block_bytes = block_size_mb * 1024 * 1024
    # Round up so the copied extent is never smaller than total_bytes (which
    # already includes the safety margin computed in
    # _source_used_extent_bytes) -- truncating short would risk cutting off
    # real partition data, not just empty trailing space.
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
                    # Short-window rate (>= 1s between samples) so it tracks
                    # the device's *current* throughput -- a lifetime average
                    # would mask exactly the kind of slow/failing transfer
                    # this is meant to surface while it's still running.
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
    except Exception as exc:
        with _status_lock:
            _status.error = str(exc)
    finally:
        with _status_lock:
            _status.running = False
            _status.done = True
            _status.finished_at = time.time()


def start_clone(target_device: str, confirm_phrase: str, block_size_mb: int = 4) -> tuple[bool, str]:
    """Validate and start a whole-disk clone in a background thread.

    Returns (accepted, message). Re-derives the source disk and the target
    allowlist fresh on every call -- a caller cannot pin an earlier scan.

    block_size_mb tunes dd's transfer chunk size: some USB-SATA/USB-IDE
    bridge chips have sustained throughput that varies a lot with this
    (the default 4 is a reasonable general-purpose value, not necessarily
    optimal for every bridge chip -- there's no way to know without trying
    on the actual hardware).
    """
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
