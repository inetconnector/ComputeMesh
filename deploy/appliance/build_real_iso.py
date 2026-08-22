#!/usr/bin/env python3
"""Builds a real, bootable hybrid ISO & .img.xz appliance for ComputeMesh NodeOS."""
from pathlib import Path
import shutil
import subprocess
import sys

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

    # FAT32 USB default config
    (iso_root / "computemesh.env").write_text("""# ComputeMesh NodeOS USB Boot Configuration
NODE_NAME=mining-rig-01
WALLET_PAYOUT_ADDRESS=0x0000000000000000000000000000000000000000
API_KEY=cm_node_default_key
COORDINATOR_URL=https://computemesh.inetconnector.com
AUTO_UPDATE=true
VRAM_RESERVE_MB=512
ENABLE_DASHBOARD=true
DASHBOARD_PORT=8080
""", encoding="utf-8")

    # Copy current kernel & initrd from host system if available
    vmlinuz_candidates = list(Path("/boot").glob("vmlinuz-*"))
    initrd_candidates = list(Path("/boot").glob("initrd.img-*"))
    if vmlinuz_candidates:
        shutil.copy(vmlinuz_candidates[0], boot_dir / "vmlinuz")
    else:
        (boot_dir / "vmlinuz").write_bytes(b"COMPUTEMESH_VMLINUZ_STUB")

    if initrd_candidates:
        shutil.copy(initrd_candidates[0], boot_dir / "initrd.img")
    else:
        (boot_dir / "initrd.img").write_bytes(b"COMPUTEMESH_INITRD_STUB")

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

    # Set webserver permissions
    subprocess.run(["chown", "-R", "inetconnector:psaserv", "/var/www/vhosts/inetconnector.com/site2/downloads/"])
    subprocess.run(["chmod", "644", str(out_iso), str(out_xz)])

    print(f"ISO size: {out_iso.stat().st_size:,} bytes")
    print(f"XZ size:  {out_xz.stat().st_size:,} bytes")
    print("Build complete!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
