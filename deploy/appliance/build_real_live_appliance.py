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

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG

BUILD_DIR = Path("/var/tmp/nodeos_live_build")
CHROOT_DIR = BUILD_DIR / "chroot"
ISO_DIR = BUILD_DIR / "iso_root"
# Staging directory for built appliance images (decoupled from live production webroot)
STAGING_DIR = Path(os.environ.get("COMPUTEMESH_IMAGE_STAGING_DIR", str(BUILD_DIR / "staging")))
OUTPUT_DIR = STAGING_DIR
DEBIAN_MIRROR = os.environ.get("COMPUTEMESH_DEBIAN_MIRROR", "http://deb.debian.org/debian").strip()
DEBIAN_KEYRING = os.environ.get(
    "COMPUTEMESH_DEBIAN_KEYRING",
    "/usr/share/keyrings/debian-archive-keyring.gpg",
).strip()
LLAMA_CPP_VERSION = "v0.4.1"
LLAMA_CPP_COMMIT = "29aaf1c27faa48292357cea2120d94114a545006"
DEFAULT_PERSISTENCE_SIZE_MIB = 65536
PROVENANCE_PREFIX = "COMPUTEMESH_BUILD_PROVENANCE_V1="
PREFLIGHT_MARKER = "/run/computemesh/node-preflight.ok"


def run(cmd: list[str], check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print(f"--> Running: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, cwd=cwd, text=True)


def chroot_exec(cmd: str) -> None:
    run(["chroot", str(CHROOT_DIR), "/bin/bash", "-c", cmd])


def _validate_debian_mirror() -> str:
    parsed = urlparse(DEBIAN_MIRROR)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("COMPUTEMESH_DEBIAN_MIRROR must be an http(s) URL")
    return DEBIAN_MIRROR


def _validate_debian_keyring() -> Path:
    """Require an explicit Debian archive keyring before debootstrap.

    Debian's debootstrap otherwise continues with only a warning when the
    host keyring is absent. That would make a successful image build
    unauthenticated at the first package boundary, so fail closed here.
    ``.gpg`` is commonly a symlink to the distro's current ``.pgp`` keyring;
    ``is_file`` intentionally follows that managed symlink.
    """
    candidate = Path(DEBIAN_KEYRING).expanduser()
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise RuntimeError(
            "COMPUTEMESH_DEBIAN_KEYRING must name a non-empty Debian archive keyring"
        )
    return candidate.resolve()


def _git_command(repo_src: Path, *arguments: str) -> list[str]:
    """Build a Git command that works for root-owned Linux/WSL builds.

    A WSL build is often run as root while the checkout is owned by the
    Windows user.  Git's safe-directory guard must be scoped to this exact
    checkout; changing global Git configuration would hide unrelated
    ownership problems and would make the build non-reproducible.
    """
    return [
        "git",
        "-c",
        f"safe.directory={repo_src}",
        "-C",
        str(repo_src),
        *arguments,
    ]


def _git_text(repo_src: Path, *arguments: str) -> str:
    result = subprocess.run(
        _git_command(repo_src, *arguments),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _validate_commit(commit: str) -> str:
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit.lower()):
        raise RuntimeError(f"invalid source commit: {commit!r}")
    return commit


def _resolve_source_repo(
    source_repo: Path | str | None = None,
    *,
    expected_commit: str | None = None,
) -> tuple[Path, str]:
    """Resolve and attest one clean regular Git checkout for the build.

    The default is this builder's own public checkout.  Operators may pass a
    different regular checkout explicitly (including a WSL-mounted path), but
    a dirty tree, a non-repository directory, a missing required source path,
    or a revision mismatch is rejected before any image work starts.
    """
    configured = source_repo or os.environ.get("COMPUTEMESH_SOURCE_REPO", "").strip()
    candidate = Path(configured) if configured else REPO_ROOT
    candidate = candidate.expanduser().resolve()
    if not candidate.is_dir():
        raise RuntimeError(f"NodeOS source repository is not a directory: {candidate}")
    try:
        git_root = Path(_git_text(candidate, "rev-parse", "--show-toplevel")).resolve()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("NodeOS source path is not a regular Git checkout") from exc
    if git_root != candidate:
        raise RuntimeError("NodeOS source path must be the Git checkout root")

    required = (
        "apps",
        "services",
        "tools",
        "runtime",
        "deploy",
        "protocol",
        "portal",
        "config.py",
        "requirements.txt",
    )
    missing = [name for name in required if not (candidate / name).exists()]
    if missing:
        raise RuntimeError(f"NodeOS source checkout is incomplete: missing {', '.join(missing)}")

    status = _git_text(candidate, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise RuntimeError("NodeOS source checkout must be clean before building")

    commit = _validate_commit(_git_text(candidate, "rev-parse", "HEAD"))
    requested = expected_commit or os.environ.get("COMPUTEMESH_EXPECTED_SOURCE_COMMIT", "").strip()
    if requested:
        requested = _validate_commit(requested)
        if requested != commit:
            raise RuntimeError(
                f"NodeOS source commit mismatch: expected {requested}, found {commit}"
            )
    return candidate, commit


def _source_commit(repo_src: Path) -> str:
    return _validate_commit(_git_text(repo_src, "rev-parse", "HEAD"))


def _provenance(repo_src: Path, source_commit: str | None = None) -> dict[str, object]:
    commit = _validate_commit(source_commit or _source_commit(repo_src))
    return {
        "schema_version": 1,
        "artifact_kind": "nodeos",
        "source_commit": commit,
        "source_tree": _validate_commit(_git_text(repo_src, "rev-parse", f"{commit}^{{tree}}")),
        "source_clean": True,
        "version": CONFIG.appliance_version,
        "llama_cpp_version": LLAMA_CPP_VERSION,
        "llama_cpp_commit": LLAMA_CPP_COMMIT,
    }


def _write_provenance(repo_src: Path, source_commit: str) -> dict[str, object]:
    data = _provenance(repo_src, source_commit)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    marker = f"{PROVENANCE_PREFIX}{canonical}\n"
    (ISO_DIR / "computemesh-build-provenance.json").write_text(marker, encoding="utf-8")
    provenance_path = CHROOT_DIR / "usr" / "share" / "computemesh" / "build-provenance.json"
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def _copy_source_snapshot(repo_src: Path, source_commit: str, destination: Path) -> None:
    """Copy only the attested Git commit, never the mutable working tree."""
    paths = ("apps", "services", "tools", "runtime", "protocol", "deploy", "portal", "config.py", "requirements.txt")
    archive_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="computemesh-source-", suffix=".tar", dir=BUILD_DIR, delete=False) as handle:
            archive_path = Path(handle.name)
            subprocess.run(
                _git_command(repo_src, "archive", "--format=tar", source_commit, "--", *paths),
                stdout=handle,
                check=True,
            )
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        with tarfile.open(archive_path, "r") as archive:
            for member in archive.getmembers():
                if not (member.isdir() or member.isreg()):
                    raise RuntimeError("Git source archive contains an unsupported special file")
                target = (destination / member.name).resolve()
                if os.path.commonpath((str(destination_root), str(target))) != str(destination_root):
                    raise RuntimeError("Git source archive contains an unsafe path")
                archive.extract(member, destination)
    except (OSError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("cannot export the attested NodeOS source commit") from exc
    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_artifact_provenance(
    output_dir: Path,
    provenance: dict[str, object],
    iso_path: Path,
    image_path: Path,
) -> Path:
    report = {
        **provenance,
        "artifacts": {
            "iso": {
                "filename": iso_path.name,
                "size_bytes": iso_path.stat().st_size,
                "sha256": _sha256(iso_path),
            },
            "img_xz": {
                "filename": image_path.name,
                "size_bytes": image_path.stat().st_size,
                "sha256": _sha256(image_path),
            },
        },
    }
    output = output_dir / "computemesh-nodeos-x86_64.provenance.json"
    temporary = output.with_name(output.name + f".tmp.{os.getpid()}")
    try:
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _render_module_launcher(
    module: str,
    arguments: str = '"$@"',
    *,
    nodeos: bool = False,
) -> str:
    """Render a cwd-independent Python module launcher for the image."""
    if not module or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._" for char in module):
        raise ValueError("invalid appliance launcher module")
    nodeos_environment = (
        "export COMPUTEMESH_NODEOS=1\n"
        f"export COMPUTEMESH_NODEOS_PREFLIGHT_MARKER={PREFLIGHT_MARKER}\n"
        if nodeos
        else ""
    )
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        "cd /opt/computemesh\n"
        "export PYTHONPATH=/opt/computemesh${PYTHONPATH:+:$PYTHONPATH}\n"
        + nodeos_environment
        + f"exec /usr/bin/python3 -m {module} {arguments}\n"
    )


def _render_preflight_unit() -> str:
    return f"""[Unit]
Description=ComputeMesh NodeOS enrollment, persistence and runtime preflight
Wants=network-online.target
After=network-online.target
Before=computemesh-node.service computemesh-node-heartbeat.service
RequiresMountsFor=/opt/computemesh /etc/computemesh /var/lib/computemesh

[Service]
Type=oneshot
WorkingDirectory=/opt/computemesh
Environment=PYTHONPATH=/opt/computemesh
Environment=COMPUTEMESH_NODEOS=1
Environment=COMPUTEMESH_NODEOS_PREFLIGHT_MARKER={PREFLIGHT_MARKER}
ExecStart=/opt/computemesh/bin/computemesh-node-preflight --ready-file {PREFLIGHT_MARKER}
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def _render_heartbeat_unit() -> str:
    return f"""[Unit]
Description=ComputeMesh authenticated NodeOS heartbeat relay
Requires=computemesh-node-preflight.service
After=computemesh-node-preflight.service network-online.target
Wants=network-online.target
ConditionPathExists=/etc/computemesh/provider.env
ConditionPathExists={PREFLIGHT_MARKER}
RequiresMountsFor=/opt/computemesh /etc/computemesh /var/lib/computemesh

[Service]
Type=simple
User=computemesh
Group=computemesh
WorkingDirectory=/opt/computemesh
EnvironmentFile=-/etc/computemesh/provider.env
Environment=PYTHONPATH=/opt/computemesh
Environment=COMPUTEMESH_NODEOS=1
Environment=COMPUTEMESH_NODEOS_PREFLIGHT_MARKER={PREFLIGHT_MARKER}
ExecStart=/usr/bin/python3 -m tools.appliance.heartbeat_relay
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/computemesh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def build_appliance(
    output_dir: Path | None = None,
    *,
    source_repo: Path | str | None = None,
    expected_source_commit: str | None = None,
) -> int:
    print("====================================================================")
    print("      Building Complete ComputeMesh Debian Live NodeOS Appliance    ")
    print("====================================================================")

    debian_mirror = _validate_debian_mirror()
    debian_keyring = _validate_debian_keyring()
    repo_src, source_commit = _resolve_source_repo(
        source_repo,
        expected_commit=expected_source_commit,
    )

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
    final_output_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    final_output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Debootstrap Base System
    print("\n[Step 1/6] Debootstrapping minimal Debian 13 (Trixie)...")
    run([
        "debootstrap",
        "--arch=amd64",
        "--variant=minbase",
        "--keyring",
        str(debian_keyring),
        "--include=systemd,systemd-sysv,udev,kmod,iproute2,isc-dhcp-client,curl,wget,ca-certificates,sudo,pciutils,usbutils,python3,python3-pip,lm-sensors,mesa-vulkan-drivers,vulkan-tools,libvulkan1,firmware-linux-free,fdisk,gdisk,parted,efibootmgr,git,cmake,ninja-build,build-essential,pkg-config,libvulkan-dev,glslc,spirv-headers",
        "trixie",
        str(CHROOT_DIR),
        debian_mirror,
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
        sources = f"""deb {debian_mirror} trixie main contrib non-free non-free-firmware
deb {debian_mirror} trixie-updates main contrib non-free non-free-firmware
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
            "nvidia-driver "
            "fdisk gdisk parted efibootmgr dosfstools "
            "xserver-xorg-core xserver-xorg-video-all xserver-xorg-input-libinput xserver-xorg-input-evdev "
            "x11-xserver-utils xinit openbox unclutter chromium"
        )

        # NodeOS ships without a shared password. Operators provision SSH keys
        # explicitly; unattended password login is disabled.
        chroot_exec("passwd -l root")
        ssh_config = CHROOT_DIR / "etc" / "ssh" / "sshd_config.d" / "live.conf"
        ssh_config.parent.mkdir(parents=True, exist_ok=True)
        ssh_config.write_text(
            "PermitRootLogin prohibit-password\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n",
            encoding="utf-8",
        )

        # Build the production model runtime from one immutable upstream commit.
        # Vulkan is the common backend for supported AMD and NVIDIA NodeOS GPUs.
        chroot_exec("git clone --filter=blob:none https://github.com/ggml-org/llama.cpp.git /tmp/llama.cpp")
        chroot_exec(f"git -C /tmp/llama.cpp checkout --detach {LLAMA_CPP_COMMIT}")
        chroot_exec(
            "cmake -S /tmp/llama.cpp -B /tmp/llama.cpp/build -G Ninja "
            "-DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON -DGGML_RPC=ON -DLLAMA_CURL=OFF "
            "-DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON"
        )
        chroot_exec("cmake --build /tmp/llama.cpp/build --target llama-server ggml-rpc-server -j2")
        chroot_exec("install -m 0755 /tmp/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server")
        # Install RPC as an opt-in binary. Never enable or publicly bind an
        # unauthenticated upstream RPC daemon automatically on NodeOS.
        chroot_exec("install -m 0755 /tmp/llama.cpp/build/bin/ggml-rpc-server /usr/local/bin/ggml-rpc-server")
        (CHROOT_DIR / "usr" / "share" / "computemesh").mkdir(parents=True, exist_ok=True)
        (CHROOT_DIR / "usr" / "share" / "computemesh" / "llama-cpp-build.txt").write_text(
            f"version={LLAMA_CPP_VERSION}\ncommit={LLAMA_CPP_COMMIT}\nbackend=vulkan\nrpc_binary_installed=1\n",
            encoding="ascii",
        )
        chroot_exec("rm -rf /tmp/llama.cpp")

        # 3. Embed ComputeMesh Codebase into /opt/computemesh
        print("\n[Step 3/6] Embedding ComputeMesh NodeOS daemon and dashboard...")
        cm_target = CHROOT_DIR / "opt" / "computemesh"
        cm_target.mkdir(parents=True, exist_ok=True)
        model_dir = CHROOT_DIR / "var" / "lib" / "computemesh" / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_dir.chmod(0o700)
        evidence_dir = CHROOT_DIR / "var" / "lib" / "computemesh" / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "EVIDENCE_REQUIRED.md").write_text(
            """# ComputeMesh NodeOS evidence is required before enrollment

This directory intentionally contains no fabricated profile or performance
numbers. Before enrollment, provision the three measured JSON documents named
by the operator enrollment bundle:

- `node_profile.json`: a local hardware/runtime inventory captured on this node;
- `prefill.json`: an actual `llama_cpp_prefill` result from the selected GGUF;
- `decode.json`: an actual `llama_cpp_decode` result from the same GGUF and
  exact llama.cpp build.

Use `tools/benchmark/benchmark.py` for the inventory and
`tools/benchmark/llama_bench_adapter.py` with the real local `llama-bench` and
GGUF for the two runtime results. Publish the resulting documents to
persistent storage only after checking the model, profile revision, build
commit, and SHA-256. `computemesh-enroll` validates all three documents before
contacting the gateway. Missing, placeholder, mismatched, or unmeasured
evidence stops enrollment with a diagnostic; it is never generated as a
default.
""",
            encoding="utf-8",
        )
        (CHROOT_DIR / "var" / "lib" / "computemesh" / "agent-environments").mkdir(parents=True, exist_ok=True)

        provenance = _write_provenance(repo_src, source_commit)
        print(
            "--> Build provenance: "
            f"source_commit={provenance['source_commit']} "
            f"version={provenance['version']}"
        )

        _copy_source_snapshot(repo_src, source_commit, cm_target)
        runtime_requirements = cm_target / "requirements.txt"
        if not runtime_requirements.is_file():
            raise RuntimeError("NodeOS build requires the repository requirements.txt")
        # Install the declared runtime set into the image.  A dependency
        # failure is a build failure; the image must not boot with a partial
        # Python environment.
        chroot_exec(
            "python3 -m pip install --no-cache-dir --break-system-packages "
            "-r /opt/computemesh/requirements.txt"
        )

        # Provision /etc/computemesh and /var/lib/computemesh state directories
        (CHROOT_DIR / "etc" / "computemesh").mkdir(parents=True, exist_ok=True)
        (CHROOT_DIR / "var" / "lib" / "computemesh").mkdir(parents=True, exist_ok=True)
        if (cm_target / "deploy" / "systemd" / "computemesh-node.service").exists():
            shutil.copy(
                cm_target / "deploy" / "systemd" / "computemesh-node.service",
                CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-node.service",
            )
        if (cm_target / "deploy" / "systemd" / "provider.env.example").exists():
            shutil.copy(
                cm_target / "deploy" / "systemd" / "provider.env.example",
                CHROOT_DIR / "etc" / "computemesh" / "provider.env.example",
            )
        enrollment_example = cm_target / "deploy" / "systemd" / "enrollment.example.json"
        if enrollment_example.is_file():
            shutil.copy(
                enrollment_example,
                CHROOT_DIR / "etc" / "computemesh" / "enrollment.example.json",
            )

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

        preflight_launcher = bin_dir / "computemesh-node-preflight"
        preflight_launcher.write_text(
            _render_module_launcher(
                "tools.appliance.boot_preflight",
                f"--ready-file {PREFLIGHT_MARKER} \"$@\"",
            ),
            encoding="utf-8",
        )
        enrollment_launcher = bin_dir / "computemesh-enroll"
        enrollment_launcher.write_text(
            _render_module_launcher("tools.appliance.enroll", nodeos=True),
            encoding="utf-8",
        )
        chroot_exec("chmod +x /opt/computemesh/bin/computemesh-node-preflight /opt/computemesh/bin/computemesh-enroll")

        preflight_unit = CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-node-preflight.service"
        preflight_unit.write_text(
            _render_preflight_unit(),
            encoding="utf-8",
        )
        heartbeat_unit = CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-node-heartbeat.service"
        heartbeat_unit.write_text(_render_heartbeat_unit(), encoding="utf-8")
        # The experimental upstream RPC daemon is strictly opt-in and binds
        # only to loopback. Never enable it during image creation.
        rpc_source = cm_target / "deploy" / "systemd" / "computemesh-rpc-worker.service"
        if not rpc_source.is_file():
            raise RuntimeError("NodeOS image lacks the protected RPC worker service contract")
        shutil.copy(
            rpc_source,
            CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-rpc-worker.service",
        )
        node_override_dir = CHROOT_DIR / "etc" / "systemd" / "system" / "computemesh-node.service.d"
        node_override_dir.mkdir(parents=True, exist_ok=True)
        (node_override_dir / "10-preflight.conf").write_text(
            """[Unit]
Requires=computemesh-node-preflight.service
After=computemesh-node-preflight.service
""",
            encoding="utf-8",
        )

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
Environment=COMPUTEMESH_LLAMA_SERVER=/usr/local/bin/llama-server
Environment=COMPUTEMESH_MODEL_DIR=/var/lib/computemesh/models
Environment=COMPUTEMESH_NODEOS=1
Environment=COMPUTEMESH_NODEOS_PREFLIGHT_MARKER=/run/computemesh/node-preflight.ok
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

        # Ensure daemon service user computemesh exists and state directories are secured (0700)
        chroot_exec("id -u computemesh >/dev/null 2>&1 || useradd -r -s /bin/false -d /var/lib/computemesh -m computemesh")
        chroot_exec("chown -R computemesh:computemesh /var/lib/computemesh /etc/computemesh")
        chroot_exec("chmod 700 /var/lib/computemesh /etc/computemesh")

        # Enable services in chroot
        chroot_exec("systemctl enable computemesh-node-preflight.service")
        chroot_exec("systemctl enable computemesh-node-heartbeat.service")
        chroot_exec("systemctl enable computemesh-appliance.service")
        chroot_exec("systemctl enable computemesh-kiosk.service")
        chroot_exec("systemctl enable computemesh-console.service")
        chroot_exec("systemctl enable computemesh-node.service")
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
COORDINATOR_URL=https://control.example.invalid
ENROLLMENT_BUNDLE=/etc/computemesh/enrollment.json
PERSISTENCE_LABEL=persistence
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
  APPEND initrd=/boot/initrd.img boot=live components quiet splash console=tty0 console=ttyS0,115200n8 systemd.show_status=1 computemesh.autostart=1 persistence persistence-label=persistence live-media-timeout=8
""",
        encoding="utf-8",
    )

    # Setup GRUB (UEFI)
    grub_dir = boot_dir / "grub"
    grub_dir.mkdir(parents=True, exist_ok=True)
    embedded_grub = """set default=0
set timeout=3
serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1
terminal_output console serial
insmod all_video
insmod font
insmod gfxterm
insmod part_gpt
insmod part_msdos
insmod fat
insmod iso9660
insmod ext2
insmod gzio

# Search for root partition by label COMPUTEMESH or by kernel file
if search --no-floppy --set=root --label COMPUTEMESH; then
    echo "Booting ComputeMesh NodeOS from volume label COMPUTEMESH..."
elif search --no-floppy --set=root --file /boot/vmlinuz; then
    echo "Booting ComputeMesh NodeOS from /boot/vmlinuz..."
fi

menuentry "ComputeMesh NodeOS (AMD / NVIDIA Native Multi-GPU)" {
    linux /boot/vmlinuz boot=live components quiet splash console=tty0 console=ttyS0,115200n8 systemd.show_status=1 computemesh.autostart=1 persistence persistence-label=persistence live-media-timeout=8
    initrd /boot/initrd.img
}

menuentry "ComputeMesh NodeOS (Debug / Verbose Console)" {
    linux /boot/vmlinuz boot=live components console=tty0 console=ttyS0,115200n8 systemd.show_status=1 computemesh.autostart=1 persistence persistence-label=persistence live-media-timeout=8
    initrd /boot/initrd.img
}
"""
    embedded_cfg = BUILD_DIR / "embedded_grub.cfg"
    embedded_cfg.write_text(embedded_grub, encoding="utf-8")
    (grub_dir / "grub.cfg").write_text(embedded_grub, encoding="utf-8")

    bootx64 = BUILD_DIR / "bootx64.efi"
    grub_modules = (
        "part_gpt part_msdos fat iso9660 ext2 squash4 "
        "search search_fs_file search_label search_fs_uuid "
        "configfile test echo normal linux boot loadenv "
        "gzio xzio zstd all_video font gfxterm video efi_gop "
        "sleep reboot halt gettext bufio"
    )
    run([
        "grub-mkstandalone",
        "-O", "x86_64-efi",
        "-o", str(bootx64),
        f"--modules={grub_modules}",
        f"boot/grub/grub.cfg={embedded_cfg}",
    ])

    efi_img = grub_dir / "efi.img"
    efi_img.write_bytes(b"\x00" * (16 * 1024 * 1024))
    run(["mkfs.vfat", str(efi_img)])
    run(["mmd", "-i", str(efi_img), "::/EFI"])
    run(["mmd", "-i", str(efi_img), "::/EFI/BOOT"])
    run(["mcopy", "-i", str(efi_img), str(bootx64), "::/EFI/BOOT/BOOTX64.EFI"])

    out_iso = final_output_dir / "computemesh-nodeos-x86_64.iso"
    out_img = final_output_dir / "computemesh-nodeos-x86_64.img"
    out_xz = final_output_dir / "computemesh-nodeos-x86_64.img.xz"
    temp_suffix = f".tmp.{os.getpid()}"
    temp_iso = final_output_dir / f"computemesh-nodeos-x86_64.iso{temp_suffix}"
    temp_img = final_output_dir / f"computemesh-nodeos-x86_64.img{temp_suffix}"
    temp_xz = Path(str(temp_img) + ".xz")
    for temporary in (temp_iso, temp_img, temp_xz):
        temporary.unlink(missing_ok=True)

    mbr_bin = "/usr/lib/ISOLINUX/isohdpfx.bin"
    run([
        "xorriso", "-as", "mkisofs",
        "-o", str(temp_iso),
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
    #
    # `live-media-timeout=8` (also wired into both boot configs above)
    # closes a second, subtler failure mode: live-boot's medium scan starts
    # scanning immediately and takes whichever device answers its label
    # search first, preferring removable devices but falling back to fixed
    # disks the instant one answers. On real hardware the USB stick (behind
    # a hub, slower to enumerate) can still be invisible to the kernel at
    # the moment the scan runs and lose the race to an internal SSD/HDD
    # that happens to carry an old COMPUTEMESH-labeled image (e.g. from a
    # prior USB->SSD clone) -- live-boot mounts that stale disk instead,
    # finds no persistence partition on it, and silently falls back to the
    # ephemeral RAM overlay, so updates appear to "vanish" on next reboot
    # even though the USB stick's own persistence partition is fine.
    #
    # An earlier version of this fix used `live-media=removable-usb`,
    # which excludes fixed disks from the scan entirely -- that closes the
    # race but also permanently breaks booting the SSD standalone once the
    # USB stick that was used to flash it is removed (live-boot then finds
    # *no* medium at all and drops to a rescue shell), which defeats the
    # actual point of the USB->SSD clone feature. `live-media-timeout=8`
    # instead only delays when the scan *starts* by up to 8 seconds,
    # giving the USB controller time to enumerate before either the
    # removable-first or the fixed-disk-fallback branch runs -- so a
    # present USB stick still reliably wins the race, but the SSD boots
    # fine on its own once the stick is unplugged for good.
    print("\nGenerating flashable .img with an ext4 persistence partition...")
    mib = 1024 * 1024
    iso_size = temp_iso.stat().st_size
    iso_size_aligned = -(-iso_size // mib) * mib  # round up to a MiB boundary
    persistence_size_mib = int(os.environ.get("COMPUTEMESH_PERSISTENCE_SIZE_MIB", str(DEFAULT_PERSISTENCE_SIZE_MIB)))
    if not 16384 <= persistence_size_mib <= 262144:
        raise RuntimeError("COMPUTEMESH_PERSISTENCE_SIZE_MIB must be between 16384 and 262144")
    total_size = iso_size_aligned + persistence_size_mib * mib

    shutil.copyfile(temp_iso, temp_img)
    with open(temp_img, "ab") as f:
        f.truncate(total_size)

    # sfdisk --append only adds a new partition entry; unlike some higher-
    # level tools it does not rewrite/renumber the existing hybrid MBR/GPT
    # entries that make the ISO9660 content BIOS+UEFI bootable, which is
    # the part that must not be disturbed.
    sfdisk_input = f"{iso_size_aligned // 512},,L\n"  # start in 512B sectors, Linux type
    subprocess.run(["sfdisk", "--append", "--no-reread", str(temp_img)], input=sfdisk_input, text=True, check=True)
    run(["partprobe", str(temp_img)], check=False)

    loop_dev = subprocess.run(
        ["losetup", "--show", "-f", "-o", str(iso_size_aligned), "--sizelimit", str(persistence_size_mib * mib), str(temp_img)],
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

    run(["xz", "-f", "-6", "-k", str(temp_img)])

    # Set permissions on staged build outputs
    try:
        run(["chmod", "644", str(temp_iso), str(temp_xz)], check=False)
    except Exception as exc:
        print(f"Notice: Artifact permissions setup: {exc}")

    # Do not expose partially written images to a release publisher.  The
    # temporary files have already completed the full build and persistence
    # formatting path before each atomic replacement below.
    os.replace(temp_iso, out_iso)
    os.replace(temp_xz, out_xz)
    temp_img.unlink(missing_ok=True)
    provenance_report = _write_artifact_provenance(
        final_output_dir,
        provenance,
        out_iso,
        out_xz,
    )

    print("\n====================================================================")
    print(f"SUCCESS: True Debian Live NodeOS Image Generated!")
    print(f"ISO File: {out_iso} ({out_iso.stat().st_size:,} bytes)")
    print(f"XZ File:  {out_xz} ({out_xz.stat().st_size:,} bytes)")
    print(f"Provenance: {provenance_report}")
    print("====================================================================")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-repo",
        type=Path,
        help="explicit regular Git checkout containing the public ComputeMesh source",
    )
    parser.add_argument(
        "--expected-source-commit",
        help="optional exact 40-character commit that must be built",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="isolated directory for the ISO, IMG.XZ and provenance report",
    )
    args = parser.parse_args()
    sys.exit(
        build_appliance(
            output_dir=args.output_dir,
            source_repo=args.source_repo,
            expected_source_commit=args.expected_source_commit,
        )
    )
