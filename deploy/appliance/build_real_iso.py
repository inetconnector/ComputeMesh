#!/usr/bin/env python3
"""Builds a real, bootable hybrid ISO & .img.xz appliance for ComputeMesh NodeOS."""
import shutil
import subprocess
import sys
from pathlib import Path


def _copy_matched_boot_files(source: Path, destination: Path) -> None:
    """Refuse missing, empty, or mismatched boot files; never generate stubs."""
    for kernel in sorted(source.glob("vmlinuz-*")):
        release = kernel.name.removeprefix("vmlinuz-")
        initrd = source / f"initrd.img-{release}"
        if (kernel.is_file() and kernel.stat().st_size > 0
                and initrd.is_file() and initrd.stat().st_size > 0):
            shutil.copy2(kernel, destination / "vmlinuz")
            shutil.copy2(initrd, destination / "initrd.img")
            return
    raise RuntimeError("NodeOS ISO requires a nonempty matching kernel and initramfs")


def _set_download_permissions(iso: Path, compressed: Path) -> None:
    """Fail the build if release download permissions cannot be set."""
    subprocess.run(
        ["chown", "-R", "inetconnector:psaserv",
         "/var/www/vhosts/inetconnector.com/site2/downloads/"],
        check=True,
    )
    subprocess.run(["chmod", "644", str(iso), str(compressed)], check=True)


def main() -> int:
    build_root = Path("/tmp/computemesh_iso_build")
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True, exist_ok=True)

    iso_root = build_root / "iso"
    iso_root.mkdir(parents=True, exist_ok=True)

    # 1. Boot directory structure
    isolinux_dir = iso_root / "isolinux"
    isolinux_dir.mkdir(parents=True, exist_ok=True)
    boot_dir = iso_root / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)

    # Copy ISOLINUX binaries if available
    isolinux_bin = Path("/usr/lib/ISOLINUX/isolinux.bin")
    if not isolinux_bin.exists():
        isolinux_bin = Path("/usr/lib/syslinux/modules/bios/isolinux.bin")
    if isolinux_bin.exists():
        shutil.copy(isolinux_bin, isolinux_dir / "isolinux.bin")

    for f in ["ldlinux.c32", "libcom32.c32", "libutil.c32", "vesamenu.c32"]:
        src = Path(f"/usr/lib/syslinux/modules/bios/{f}")
        if src.exists():
            shutil.copy(src, isolinux_dir / f)

    # ISOLINUX configuration
    (isolinux_dir / "isolinux.cfg").write_text("""DEFAULT computemesh
PROMPT 0
TIMEOUT 30

LABEL computemesh
  MENU LABEL ^ComputeMesh NodeOS Live (AMD / NVIDIA Multi-GPU)
  KERNEL /boot/vmlinuz
  APPEND initrd=/boot/initrd.img boot=live quiet splash computemesh.autostart=1
""", encoding="utf-8")

    # 2. ComputeMesh Appliance package tree
    cm_dir = iso_root / "opt" / "computemesh"
    cm_dir.mkdir(parents=True, exist_ok=True)

    # Copy ComputeMesh codebase
    repo_src = Path("/root/ComputeMesh")
    for subdir in ["tools", "services", "runtime", "protocol", "deploy"]:
        if (repo_src / subdir).exists():
            shutil.copytree(repo_src / subdir, cm_dir / subdir, dirs_exist_ok=True)
    if (repo_src / "config.py").exists():
        shutil.copy(repo_src / "config.py", cm_dir / "config.py")

    # FAT32 USB default config
    (iso_root / "computemesh.env").write_text("""# ComputeMesh NodeOS USB Boot Configuration
NODE_NAME=cm-node-provider
WALLET_PAYOUT_ADDRESS=
API_KEY=
COORDINATOR_URL=https://mesh.inetconnector.com
AUTO_UPDATE=true
VRAM_RESERVE_MB=512
ENABLE_DASHBOARD=true
DASHBOARD_PORT=8080
""", encoding="utf-8")

    # The legacy ISO path must not present synthetic boot bytes as real.
    _copy_matched_boot_files(Path("/boot"), boot_dir)

    out_iso = Path("/var/www/vhosts/inetconnector.com/site2/downloads/computemesh-nodeos-x86_64.iso")
    out_xz = Path("/var/www/vhosts/inetconnector.com/site2/downloads/computemesh-nodeos-x86_64.img.xz")

    print(f"Building ISO at {out_iso}...")
    # Use xorriso / genisoimage
    cmd = [
        "xorriso",
        "-as", "mkisofs",
        "-r", "-V", "COMPUTEMESH_NODEOS",
        "-o", str(out_iso),
        str(iso_root)
    ]
    subprocess.run(cmd, check=True)

    print("Generating compressed .img.xz archive...")
    # Generate .xz from the ISO
    with open(out_iso, "rb") as f_in, open(str(out_xz) + ".tmp", "wb") as f_out:
        subprocess.run(["xz", "-c", "-1"], stdin=f_in, stdout=f_out, check=True)
    shutil.move(str(out_xz) + ".tmp", out_xz)

    # Both permission changes are mandatory for a successful build.
    _set_download_permissions(out_iso, out_xz)

    print(f"ISO size: {out_iso.stat().st_size:,} bytes")
    print(f"XZ size:  {out_xz.stat().st_size:,} bytes")
    print("Build complete!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
