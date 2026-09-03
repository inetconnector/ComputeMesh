#!/usr/bin/env python3
"""ComputeMesh Full Debian Live NodeOS Builder (Turnkey Appliance).

Automates the complete generation of a full Debian 13 (Trixie) Live USB system:
1. Debootstrap minimal Debian 13 root filesystem
2. Installs kernel, live-boot, GPU firmware, Vulkan/CUDA drivers, Python runtime
3. Embeds ComputeMesh node daemon and live dashboard (port 8080)
4. Configures systemd autostart services & tty1 live console status
5. Compresses into live/filesystem.squashfs
6. Produces True Hybrid Bootable ISO (.iso) and raw flashable (.img.xz) with MBR & UEFI tables.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

BUILD_DIR = Path("/var/tmp/nodeos_live_build")
CHROOT_DIR = BUILD_DIR / "chroot"
ISO_DIR = BUILD_DIR / "iso_root"
DEBIAN_MIRROR = "http://debian.anexia.at/debian"
OUTPUT_DIR = Path("/var/www/vhosts/inetconnector.com/site2/downloads")


def run(cmd: list[str], check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print(f"--> Running: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, cwd=cwd, text=True)


def chroot_exec(cmd: str) -> None:
    run(["chroot", str(CHROOT_DIR), "/bin/bash", "-c", cmd])


def build_appliance() -> int:
    print("====================================================================")
    print("      Building Complete ComputeMesh Debian Live NodeOS Appliance    ")
    print("====================================================================")

    if BUILD_DIR.exists():
        print(f"Cleaning up previous build directory at {BUILD_DIR}...")
        # Unmount any mounts inside chroot if any
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "dev" / "pts")], stderr=subprocess.DEVNULL)
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "dev")], stderr=subprocess.DEVNULL)
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "proc")], stderr=subprocess.DEVNULL)
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "sys")], stderr=subprocess.DEVNULL)
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    CHROOT_DIR.mkdir(parents=True, exist_ok=True)
    ISO_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Debootstrap Base System
    print("\n[Step 1/6] Debootstrapping minimal Debian 13 (Trixie)...")
    run([
        "debootstrap",
        "--arch=amd64",
        "--variant=minbase",
        "--include=systemd,systemd-sysv,udev,kmod,iproute2,isc-dhcp-client,curl,wget,ca-certificates,sudo,pciutils,usbutils,python3,python3-pip,lm-sensors,mesa-vulkan-drivers,vulkan-tools,libvulkan1,firmware-linux-free",
        "trixie",
        str(CHROOT_DIR),
        DEBIAN_MIRROR,
    ])

    # 2. Configure Chroot & Install Kernel & Live-Boot
    print("\n[Step 2/6] Configuring live system, kernel, and packages...")
    
    # Mount virtual filesystems for chroot
    run(["mount", "--bind", "/dev", str(CHROOT_DIR / "dev")])
    run(["mount", "--bind", "/dev/pts", str(CHROOT_DIR / "dev" / "pts")])
    run(["mount", "-t", "proc", "proc", str(CHROOT_DIR / "proc")])
    run(["mount", "-t", "sysfs", "sysfs", str(CHROOT_DIR / "sys")])

    try:
        # Configure sources.list for non-free & firmware
        sources = f"""deb {DEBIAN_MIRROR} trixie main contrib non-free non-free-firmware
deb {DEBIAN_MIRROR} trixie-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
"""
        (CHROOT_DIR / "etc" / "apt" / "sources.list").write_text(sources, encoding="utf-8")

        # Hostname & Network
        (CHROOT_DIR / "etc" / "hostname").write_text("computemesh-nodeos\n", encoding="utf-8")
        (CHROOT_DIR / "etc" / "hosts").write_text("127.0.0.1 localhost computemesh-nodeos\n", encoding="utf-8")

        chroot_exec("apt-get update")
        chroot_exec(
            "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "
            "linux-image-amd64 live-boot live-config systemd-timesyncd systemd-resolved openssh-server firmware-amd-graphics firmware-misc-nonfree "
            "xserver-xorg-core xserver-xorg-video-all xserver-xorg-input-libinput xserver-xorg-input-evdev "
            "x11-xserver-utils xinit openbox unclutter chromium"
        )

        # Set root password to computemesh
        chroot_exec("echo 'root:computemesh' | chpasswd")
        # Enable SSH root login with password
        ssh_config = CHROOT_DIR / "etc" / "ssh" / "sshd_config.d" / "live.conf"
        ssh_config.parent.mkdir(parents=True, exist_ok=True)
        ssh_config.write_text("PermitRootLogin yes\nPasswordAuthentication yes\n", encoding="utf-8")

        # 3. Embed ComputeMesh Codebase into /opt/computemesh
        print("\n[Step 3/6] Embedding ComputeMesh NodeOS daemon and dashboard...")
        cm_target = CHROOT_DIR / "opt" / "computemesh"
        cm_target.mkdir(parents=True, exist_ok=True)

        repo_src = Path("/root/ComputeMesh")
        if not repo_src.exists():
            repo_src = Path("/var/www/vhosts/inetconnector.com/site2")
        
        for subdir in ["tools", "services", "runtime", "protocol", "deploy"]:
            src = repo_src / subdir
            if src.exists():
                shutil.copytree(src, cm_target / subdir, dirs_exist_ok=True)
        if (repo_src / "config.py").exists():
            shutil.copy(repo_src / "config.py", cm_target / "config.py")

        # Install launcher script
        bin_dir = cm_target / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        launcher_script = bin_dir / "computemesh-node"
        launcher_script.write_text(
            """#!/usr/bin/env python3
import sys
from pathlib import Path
REPO = Path('/opt/computemesh')
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from services.appliance_dashboard.server import main
if __name__ == '__main__':
    sys.exit(main())
""",
            encoding="utf-8",
        )
        chroot_exec("chmod +x /opt/computemesh/bin/computemesh-node")

        # Install Kiosk Fullscreen Launcher
        kiosk_script = bin_dir / "start-kiosk.sh"
        kiosk_script.write_text(
            """#!/bin/bash
# Wait for appliance web server to respond
for i in {1..30}; do
    if curl -s http://127.0.0.1:8080/ >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

xset -dpms s off s noblank 2>/dev/null || true
unclutter -idle 1 -root &
openbox &

exec /usr/bin/chromium \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 \
  --no-first-run \
  --disable-features=Translate \
  --autoplay-policy=no-user-gesture-required \
  --no-sandbox \
  --disable-gpu-sandbox \
  http://127.0.0.1:8080/
""",
            encoding="utf-8",
        )
        chroot_exec("chmod +x /opt/computemesh/bin/start-kiosk.sh")

        # Install systemd service for appliance daemon & dashboard
        appliance_unit = CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-appliance.service"
        appliance_unit.write_text(
            """[Unit]
Description=ComputeMesh NodeOS Autonomous Provider Appliance & Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/computemesh/bin/computemesh-node --port 8080
Restart=always
RestartSec=5
WorkingDirectory=/opt/computemesh
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
""",
            encoding="utf-8",
        )

        # Install Graphical Fullscreen Kiosk Service
        kiosk_unit = CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-kiosk.service"
        kiosk_unit.write_text(
            """[Unit]
Description=ComputeMesh Graphical Fullscreen Kiosk Dashboard
After=computemesh-appliance.service
Wants=computemesh-appliance.service

[Service]
Type=simple
User=root
Environment=DISPLAY=:0
ExecStart=/usr/bin/xinit /opt/computemesh/bin/start-kiosk.sh -- :0 vt7 -nocursor
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
""",
            encoding="utf-8",
        )

        # Install tty1 Live Display Service (Fallback Console Display)
        tty1_banner = CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-console.service"
        tty1_banner.write_text(
            """[Unit]
Description=ComputeMesh Graphical Fullscreen Kiosk Dashboard
After=computemesh-appliance.service
Wants=computemesh-appliance.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /opt/computemesh/tools/appliance/console_monitor.py
Restart=always
RestartSec=5
StandardInput=tty
StandardOutput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes

[Install]
WantedBy=multi-user.target
""",
            encoding="utf-8",
        )

        # Enable services in chroot
        chroot_exec("systemctl enable computemesh-appliance.service")
        chroot_exec("systemctl enable computemesh-kiosk.service")
        chroot_exec("systemctl enable computemesh-console.service")
        chroot_exec("systemctl enable systemd-networkd")
        chroot_exec("systemctl enable systemd-resolved")

        # Network auto-dhcp configuration
        net_conf = CHROOT_DIR / "etc" / "systemd" / "network" / "20-wired.network"
        net_conf.parent.mkdir(parents=True, exist_ok=True)
        net_conf.write_text("[Match]\nName=en* eth*\n\n[Network]\nDHCP=yes\n", encoding="utf-8")

        # Clean apt cache
        chroot_exec("apt-get clean")
        chroot_exec("rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*")

    finally:
        # Unmount chroot
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "dev" / "pts")], stderr=subprocess.DEVNULL)
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "dev")], stderr=subprocess.DEVNULL)
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "proc")], stderr=subprocess.DEVNULL)
        subprocess.run(["umount", "-f", str(CHROOT_DIR / "sys")], stderr=subprocess.DEVNULL)

    # 4. Extract Kernel and Initrd from Chroot
    print("\n[Step 4/6] Extracting live kernel and initrd...")
    boot_dir = ISO_DIR / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    
    vmlinuz_files = list((CHROOT_DIR / "boot").glob("vmlinuz-*"))
    initrd_files = list((CHROOT_DIR / "boot").glob("initrd.img-*"))
    
    if not vmlinuz_files or not initrd_files:
        raise RuntimeError("Kernel or initrd not found in chroot /boot!")
        
    shutil.copy(vmlinuz_files[0], boot_dir / "vmlinuz")
    shutil.copy(initrd_files[0], boot_dir / "initrd.img")

    # 5. Build SquashFS Root Filesystem
    print("\n[Step 5/6] Compressing full rootfs into live/filesystem.squashfs...")
    live_dir = ISO_DIR / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    squashfs_path = live_dir / "filesystem.squashfs"
    if squashfs_path.exists():
        squashfs_path.unlink()

    run([
        "mksquashfs",
        str(CHROOT_DIR),
        str(squashfs_path),
        "-comp", "xz",
        "-b", "1048576",
        "-Xbcj", "x86",
        "-e", "boot",
    ])

    # Default USB config template on root of ISO
    (ISO_DIR / "computemesh.env").write_text(
        """# ComputeMesh NodeOS USB Boot Configuration
NODE_NAME=cm-node-provider
WALLET_PAYOUT_ADDRESS=
API_KEY=
COORDINATOR_URL=https://mesh.inetconnector.com
AUTO_UPDATE=true
VRAM_RESERVE_MB=512
ENABLE_DASHBOARD=true
DASHBOARD_PORT=8080
""",
        encoding="utf-8",
    )

    # 6. Setup Bootloaders & Build Hybrid ISO
    print("\n[Step 6/6] Generating True Hybrid Bootable ISO (BIOS + UEFI)...")
    
    # Setup ISOLINUX (BIOS)
    isolinux_dir = ISO_DIR / "isolinux"
    isolinux_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy("/usr/lib/ISOLINUX/isolinux.bin", isolinux_dir)
    for f in ["ldlinux.c32", "libutil.c32", "menu.c32"]:
        src = Path(f"/usr/lib/syslinux/modules/bios/{f}")
        if src.exists():
            shutil.copy(src, isolinux_dir)

    (isolinux_dir / "isolinux.cfg").write_text(
        """DEFAULT computemesh
PROMPT 0
TIMEOUT 30

LABEL computemesh
  MENU LABEL ^ComputeMesh NodeOS Live (AMD / NVIDIA Multi-GPU)
  KERNEL /boot/vmlinuz
  APPEND initrd=/boot/initrd.img boot=live components quiet splash computemesh.autostart=1 persistence
""",
        encoding="utf-8",
    )

    # Setup GRUB (UEFI)
    grub_dir = boot_dir / "grub"
    grub_dir.mkdir(parents=True, exist_ok=True)
    embedded_grub = """set default=0
set timeout=3
search --set=root --file /boot/vmlinuz
menuentry "ComputeMesh NodeOS Live (AMD / NVIDIA Multi-GPU)" {
    linux /boot/vmlinuz boot=live components quiet splash computemesh.autostart=1 persistence
    initrd /boot/initrd.img
}
"""
    embedded_cfg = BUILD_DIR / "embedded_grub.cfg"
    embedded_cfg.write_text(embedded_grub, encoding="utf-8")
    (grub_dir / "grub.cfg").write_text(embedded_grub, encoding="utf-8")

    bootx64 = BUILD_DIR / "bootx64.efi"
    run([
        "grub-mkstandalone",
        "-O", "x86_64-efi",
        "-o", str(bootx64),
        "--modules=part_gpt part_msdos fat iso9660 search search_fs_file configfile test echo normal linux",
        f"boot/grub/grub.cfg={embedded_cfg}",
    ])

    efi_img = grub_dir / "efi.img"
    efi_img.write_bytes(b"\x00" * (16 * 1024 * 1024))
    run(["mkfs.vfat", str(efi_img)])
    run(["mmd", "-i", str(efi_img), "::/EFI"])
    run(["mmd", "-i", str(efi_img), "::/EFI/BOOT"])
    run(["mcopy", "-i", str(efi_img), str(bootx64), "::/EFI/BOOT/BOOTX64.EFI"])

    out_iso = OUTPUT_DIR / "computemesh-nodeos-x86_64.iso"
    out_img = OUTPUT_DIR / "computemesh-nodeos-x86_64.img"
    out_xz = OUTPUT_DIR / "computemesh-nodeos-x86_64.img.xz"

    mbr_bin = "/usr/lib/ISOLINUX/isohdpfx.bin"
    run([
        "xorriso", "-as", "mkisofs",
        "-o", str(out_iso),
        "-V", "COMPUTEMESH",
        "-r", "-J", "-joliet-long",
        "-isohybrid-mbr", mbr_bin,
        "-b", "isolinux/isolinux.bin",
        "-c", "isolinux/boot.cat",
        "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
        "-eltorito-alt-boot",
        "-e", "boot/grub/efi.img",
        "-no-emul-boot",
        "-isohybrid-gpt-basdat",
        str(ISO_DIR),
    ])

    # Generate raw flashable .img with an appended, ext4-formatted
    # "persistence" partition. Only the .img gets this -- the .iso is left
    # exactly as xorriso produced it (unmodified, for CD/DVD/VM use), so a
    # mistake here can never affect ISO boots. Without this, every config
    # change, ComputeMesh app update, and `apt-get upgrade` was silently
    # discarded on the next physical reboot: this appliance boots from a
    # read-only squashfs with a RAM-backed overlay by default, which
    # live-boot's initramfs only replaces with something durable when it
    # finds a partition/filesystem labeled "persistence" *and* the kernel
    # was given the `persistence` boot parameter (both are wired in above).
    # persistence.conf's "/ union" persists the *entire* root filesystem,
    # not just specific paths, so OS package upgrades are covered the same
    # way app updates and ~/.computemesh config are.
    print("\nGenerating flashable .img with an ext4 persistence partition...")
    mib = 1024 * 1024
    iso_size = out_iso.stat().st_size
    iso_size_aligned = -(-iso_size // mib) * mib  # round up to a MiB boundary
    persistence_size_mib = 8192  # 8 GiB: OS upgrades + app updates over time
    total_size = iso_size_aligned + persistence_size_mib * mib

    shutil.copyfile(out_iso, out_img)
    with open(out_img, "ab") as f:
        f.truncate(total_size)

    # sfdisk --append only adds a new partition entry; unlike some higher-
    # level tools it does not rewrite/renumber the existing hybrid MBR/GPT
    # entries that make the ISO9660 content BIOS+UEFI bootable, which is
    # the part that must not be disturbed.
    sfdisk_input = f"{iso_size_aligned // 512},,L\n"  # start in 512B sectors, Linux type
    subprocess.run(["sfdisk", "--append", "--no-reread", str(out_img)], input=sfdisk_input, text=True, check=True)
    run(["partprobe", str(out_img)], check=False)

    loop_dev = subprocess.run(
        ["losetup", "--show", "-f", "-o", str(iso_size_aligned), "--sizelimit", str(persistence_size_mib * mib), str(out_img)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    try:
        run(["mkfs.ext4", "-F", "-L", "persistence", loop_dev])
        mount_point = BUILD_DIR / "persistence_mount"
        mount_point.mkdir(parents=True, exist_ok=True)
        run(["mount", loop_dev, str(mount_point)])
        try:
            (mount_point / "persistence.conf").write_text("/ union\n", encoding="utf-8")
        finally:
            run(["umount", str(mount_point)])
    finally:
        run(["losetup", "-d", loop_dev])

    run(["xz", "-f", "-6", "-k", str(out_img)])

    # Fix permissions
    run(["chown", "-R", "inetconnector:psaserv", str(OUTPUT_DIR)])
    run(["chmod", "644", str(out_iso), str(out_xz)])

    print("\n====================================================================")
    print(f"SUCCESS: True Debian Live NodeOS Image Generated!")
    print(f"ISO File: {out_iso} ({out_iso.stat().st_size:,} bytes)")
    print(f"XZ File:  {out_xz} ({out_xz.stat().st_size:,} bytes)")
    print("====================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(build_appliance())
