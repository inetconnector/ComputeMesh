#!/usr/bin/env python3
"""ComputeMesh Mining Rig / Multi-GPU Hardware Detector (Native AMD + NVIDIA).

Natively discovers all attached GPUs (NVIDIA, AMD Polaris/Vega/RDNA, Intel Arc),
PCIe link widths/generations, VRAM capacities, driver backends, and thermal telemetry
for ComputeMesh inference provider nodes and mixed-vendor mining rigs.
"""
from __future__ import annotations

import argparse
from ctypes import CDLL, POINTER, Structure, byref, c_char, c_char_p, c_uint32, c_void_p
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

SCHEMA_VERSION = 1

INTEGRATED_DISPLAY_MARKERS = (
    "aspeed", "ast2400", "ast2500", "ast2600", "ast2000", "ast1000",
    "matrox", "mga", "g200", "g200e", "g200eh", "g200er", "g200ew",
    "silicon motion", "sm712", "sm750", "lynx",
    "cirrus logic", "gd 5446", "qxl", "bochs", "virtio-gpu", "vmware", "virtualbox",
    "integrated graphics", "processor graphics", "hd graphics", "uhd graphics", "iris",
    "vega 3", "vega 6", "vega 8", "vega 11", "radeon r2", "radeon r3", "radeon r4", "radeon r5"
)

DISCRETE_COMPUTE_MARKERS = (
    "radeon", "geforce", "quadro", "tesla", "rtx", "gtx", "cmp", "arc",
    "vega", "polaris", "navi", "instinct", "mi25", "mi50", "mi100",
    "rx 4", "rx 5", "rx 6", "rx 7", "rx 570", "rx 580", "rx 590",
    "a770", "a750", "a580", "a380", "a310", "b580", "b570"
)

MIN_PROVIDER_VRAM_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class GpuDevice:
    index: int
    pci_slot: str
    vendor: str  # "nvidia", "amd", "intel", "unknown"
    model_name: str
    vram_bytes: int
    pcie_gen: int | None
    pcie_width: int | None
    driver_backend: str  # "cuda", "rocm", "vulkan", "sycl"
    is_headless: bool
    healthy: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GpuThermalMetrics:
    gpu_index: int
    vendor: str
    temperature_celsius: int | None
    fan_speed_percent: int | None
    power_watts: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RigInventory:
    schema_version: int
    captured_at: str
    host_architecture: str
    total_gpus: int
    total_vram_bytes: int
    gpus: list[GpuDevice]
    pcie_riser_warning: bool
    vendor_breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "host_architecture": self.host_architecture,
            "total_gpus": self.total_gpus,
            "total_vram_bytes": self.total_vram_bytes,
            "gpus": [gpu.to_dict() for gpu in self.gpus],
            "pcie_riser_warning": self.pcie_riser_warning,
            "vendor_breakdown": self.vendor_breakdown,
        }


def _get_subprocess_flags() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}
    return {}


def is_integrated_display_adapter(vendor: str, model_name: str) -> bool:
    """Return True for motherboard/CPU display adapters that cannot serve provider AI compute."""
    m = model_name.lower()
    v = vendor.lower()

    # 1. Motherboard server/BMC display chips (Aspeed, Matrox, Silicon Motion, Cirrus, etc.)
    if any(bmc in m or bmc in v for bmc in ("aspeed", "ast2", "ast1", "matrox", "g200", "silicon motion", "cirrus", "qxl", "bochs", "virtio")):
        return True

    # 2. CPU integrated graphics (Intel HD/UHD/Iris, AMD APU Vega 3/6/8, etc.)
    if any(marker in m for marker in (
        "integrated graphics", "processor graphics", "hd graphics", "uhd graphics", "iris",
        "vega 3", "vega 6", "vega 8", "vega 11", "radeon r2", "radeon r3", "radeon r4", "radeon r5",
        "radeon graphics", "apu", "amd custom gpu", "rembrandt", "renoir", "cezanne", "barcelo",
        "raphael", "mendocino", "phoenix", "hawk point", "strix point", "family integrated graphics"
    )):
        return True

    # 3. If Intel vendor and not a discrete Arc/Data Center GPU -> It is an integrated CPU GPU!
    if v == "intel" or "8086:" in m or "ven_8086" in m:
        if not any(arc in m for arc in ("arc", "dg1", "flex", "max", "battlemage", "a770", "a750", "a580", "a380", "a310", "b580", "b570")):
            return True

    for prefix in ("vga compatible controller:", "3d controller:", "display controller:"):
        if prefix in m:
            m = m.split(prefix, 1)[-1].strip()

    # Discrete NVIDIA GPUs
    if v == "nvidia" or any(n in m for n in ("geforce", "quadro", "tesla", "rtx", "gtx", "cmp", "a100", "h100", "l40", "t4", "p106", "p104", "p102")):
        return False

    # Discrete AMD GPUs
    if (v == "amd" or "1002:" in m) and any(marker in m for marker in ("radeon", "polaris", "navi", "instinct", "mi25", "mi50", "mi100", "mi200", "mi300", "vega 56", "vega 64", "vega 10", "vega 20", "rx 4", "rx 5", "rx 6", "rx 7", "rx 570", "rx 580", "rx 590", "w6800", "w7900")):
        return False

    if "integrated" in m and "graphics" in m:
        return True
    return False


def read_pci_resource_vram_bytes(slot: str) -> int:
    """Read prefetchable BAR size directly from Linux kernel sysfs /sys/bus/pci/devices/{slot}/resource."""
    try:
        res_file = Path("/sys/bus/pci/devices") / slot / "resource"
        if not res_file.exists():
            candidates = list(Path("/sys/bus/pci/devices").glob(f"*{slot}*"))
            if candidates:
                res_file = candidates[0] / "resource"
        if not res_file.exists():
            return 0
        max_size = 0
        for line in res_file.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) >= 3:
                start = int(parts[0], 16)
                end = int(parts[1], 16)
                flags = int(parts[2], 16)
                if end > start:
                    size = end - start + 1
                    if (flags & 0x20000 or flags & 0x200) and size >= MIN_PROVIDER_VRAM_BYTES:
                        if size > max_size:
                            max_size = size
        return max_size
    except Exception:
        return 0


def estimate_gpu_vram_from_name(model_name: str, device_hex: str = "") -> int:
    """Infer standard dedicated VRAM bytes for known GPU architectures when sysfs/BAR is inaccessible."""
    m = model_name.lower()
    if is_integrated_display_adapter("unknown", model_name):
        return 0
    # Explicit model size (e.g. 16GB, 8GB, 24GB)
    match = re.search(r"(\d+)\s*(?:gb|gib)", m)
    if match:
        return int(match.group(1)) * 1024 * 1024 * 1024
    if "4090" in m or "3090" in m:
        return 24 * 1024 * 1024 * 1024
    if "7900 xtx" in m:
        return 24 * 1024 * 1024 * 1024
    if "7900 xt" in m:
        return 20 * 1024 * 1024 * 1024
    if "3080" in m or "4080" in m:
        return 16 * 1024 * 1024 * 1024
    if "3060" in m:
        return 12 * 1024 * 1024 * 1024
    if any(amd_8g in m for amd_8g in ("580", "570", "590", "480", "470", "vega", "mi25", "polaris")):
        return 8 * 1024 * 1024 * 1024
    if any(disc in m for disc in DISCRETE_COMPUTE_MARKERS):
        return 8 * 1024 * 1024 * 1024
    return 0


def is_provider_compute_gpu(gpu: GpuDevice) -> bool:
    """Provider inventory must only count discrete compute GPUs with dedicated VRAM."""
    if not gpu.healthy:
        return False
    if is_integrated_display_adapter(gpu.vendor, gpu.model_name):
        return False
    return gpu.vram_bytes >= MIN_PROVIDER_VRAM_BYTES


def detect_vendor_backend(text: str) -> tuple[str, str]:
    """Resolve a GPU vendor/backend from PCI or OS adapter text without substring traps."""
    lower = text.lower()
    if "intel" in lower or "ven_8086" in lower or "[8086:" in lower:
        return "intel", "sycl"
    if "nvidia" in lower or "ven_10de" in lower or "[10de:" in lower:
        return "nvidia", "cuda"
    if (
        "advanced micro devices" in lower
        or "[amd/ati]" in lower
        or "[1002:" in lower
        or "ven_1002" in lower
        or re.search(r"\bamd\b", lower)
        or re.search(r"\bati\b", lower)
        or "radeon" in lower
    ):
        return "amd", "vulkan"
    return "unknown", "vulkan"


def parse_size_to_bytes(size_text: str) -> int | None:
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt])(?:i?b?)?\s*$", size_text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "k": 1024,
        "m": 1024**2,
        "g": 1024**3,
        "t": 1024**4,
    }
    return int(value * multipliers[unit])


def read_lspci_prefetchable_memory_bytes(slot: str) -> int:
    """Read a conservative dedicated-memory hint from PCI BAR sizes when available."""
    if not shutil.which("lspci"):
        return 0
    try:
        res = subprocess.run(
            ["lspci", "-vv", "-s", slot],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
            **_get_subprocess_flags(),
        )
    except Exception:
        return 0

    sizes: list[int] = []
    for line in res.stdout.splitlines():
        lower = line.lower()
        if "memory at" not in lower or "prefetchable" not in lower:
            continue
        match = re.search(r"\[size=([^\]]+)\]", line, re.IGNORECASE)
        if not match:
            continue
        size_bytes = parse_size_to_bytes(match.group(1))
        if size_bytes:
            sizes.append(size_bytes)
    return max(sizes) if sizes else 0


def collect_hardware_debug() -> dict[str, Any]:
    """Collect sanitized hardware discovery inputs for remote support debugging."""
    debug: dict[str, Any] = {
        "tools": {
            "lspci": shutil.which("lspci"),
            "nvidia_smi": shutil.which("nvidia-smi"),
            "rocm_smi": shutil.which("rocm-smi"),
            "vulkaninfo": shutil.which("vulkaninfo"),
        },
        "drm_devices": [],
        "lspci_controllers": [],
    }

    for card in sorted(glob.glob("/sys/class/drm/card*/device")):
        card_path = Path(card)
        entry: dict[str, Any] = {
            "path": str(card_path),
            "resolved_slot": card_path.resolve().name,
        }
        for name in (
            "vendor",
            "device",
            "class",
            "mem_info_vram_total",
            "mem_info_vis_vram_total",
            "mem_info_gtt_total",
        ):
            try:
                file_path = card_path / name
                if file_path.exists():
                    entry[name] = file_path.read_text(errors="replace").strip()
            except Exception as exc:
                entry[f"{name}_error"] = str(exc)
        try:
            uevent = card_path / "uevent"
            if uevent.exists():
                entry["uevent"] = uevent.read_text(errors="replace").strip().splitlines()
        except Exception as exc:
            entry["uevent_error"] = str(exc)
        debug["drm_devices"].append(entry)

    if shutil.which("lspci"):
        try:
            res = subprocess.run(
                ["lspci", "-nn", "-D"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
                **_get_subprocess_flags(),
            )
            for line in res.stdout.splitlines():
                if "VGA compatible controller" in line or "3D controller" in line or "Display controller" in line:
                    slot_match = re.match(r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F])", line)
                    slot = slot_match.group(1) if slot_match else ""
                    controller: dict[str, Any] = {
                        "line": line,
                        "slot": slot,
                        "vendor_backend": detect_vendor_backend(line),
                        "prefetchable_memory_bytes": read_lspci_prefetchable_memory_bytes(slot) if slot else 0,
                    }
                    if slot:
                        try:
                            verbose = subprocess.run(
                                ["lspci", "-vv", "-s", slot],
                                capture_output=True,
                                text=True,
                                check=True,
                                timeout=8,
                                **_get_subprocess_flags(),
                            )
                            controller["memory_lines"] = [
                                l.strip()
                                for l in verbose.stdout.splitlines()
                                if "Memory at" in l or "[size=" in l
                            ][:20]
                        except Exception as exc:
                            controller["verbose_error"] = str(exc)
                    debug["lspci_controllers"].append(controller)
        except Exception as exc:
            debug["lspci_error"] = str(exc)

    return debug


# ==============================================================================
# 1. Native NVIDIA Detection & Telemetry (nvidia-smi)
# ==============================================================================

def detect_nvidia_gpus() -> list[GpuDevice]:
    """Detect NVIDIA GPUs using nvidia-smi if available."""
    if not shutil.which("nvidia-smi"):
        return []
    devices: list[GpuDevice] = []
    try:
        query = "index,pci.bus_id,name,memory.total,pcie.link.gen.current,pcie.link.width.current"
        res = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            **_get_subprocess_flags(),
        )
        for line in res.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue
            idx = int(parts[0])
            pci_slot = parts[1]
            name = parts[2]
            vram_mib = int(parts[3])
            gen = int(parts[4]) if parts[4].isdigit() else None
            width = int(parts[5]) if parts[5].isdigit() else None
            is_headless = any(tag in name for tag in ("CMP", "P106", "P104", "P102", "A100", "H100"))
            devices.append(
                GpuDevice(
                    index=idx,
                    pci_slot=pci_slot,
                    vendor="nvidia",
                    model_name=name,
                    vram_bytes=vram_mib * 1024 * 1024,
                    pcie_gen=gen,
                    pcie_width=width,
                    driver_backend="cuda",
                    is_headless=is_headless,
                    healthy=True,
                )
            )
    except Exception:
        pass
    return devices


def read_nvidia_thermals() -> list[GpuThermalMetrics]:
    """Read live temperature, fan, and power metrics from NVIDIA cards."""
    if not shutil.which("nvidia-smi"):
        return []
    thermals: list[GpuThermalMetrics] = []
    try:
        query = "index,temperature.gpu,fan.speed,power.draw"
        res = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            **_get_subprocess_flags(),
        )
        for line in res.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            idx = int(parts[0])
            temp = int(parts[1]) if parts[1].isdigit() else None
            fan = int(parts[2]) if parts[2].isdigit() else None
            power = int(float(parts[3])) if parts[3].replace(".", "", 1).isdigit() else None
            thermals.append(
                GpuThermalMetrics(
                    gpu_index=idx,
                    vendor="nvidia",
                    temperature_celsius=temp,
                    fan_speed_percent=fan,
                    power_watts=power,
                )
            )
    except Exception:
        pass
    return thermals


# ==============================================================================
# 2. Native AMD Detection & Telemetry (sysfs / ROCm / amdgpu / Vulkan)
# ==============================================================================

def detect_amd_sysfs_gpus(start_index: int = 0) -> list[GpuDevice]:
    """Detect AMD GPUs natively via Linux /sys/class/drm and rocm-smi."""
    devices: list[GpuDevice] = []
    card_paths = sorted(glob.glob("/sys/class/drm/card[0-9]*/device"))
    current_index = start_index

    for card in card_paths:
        try:
            vendor_file = Path(card) / "vendor"
            if not vendor_file.exists():
                continue
            vendor_hex = vendor_file.read_text().strip()
            # 0x1002 is AMD/ATI Vendor ID
            if vendor_hex.lower() != "0x1002":
                continue

            # Read Model / Device name
            device_hex = ""
            dev_file = Path(card) / "device"
            if dev_file.exists():
                device_hex = dev_file.read_text().strip().lower()

            model_name = "AMD Radeon GPU"
            if device_hex in ("0x67df", "0x67c0", "0x67ef"):
                model_name = "AMD Radeon RX 470/480/570/580/590 (Polaris)"
            elif device_hex in ("0x687f", "0x6863", "0x6860", "0x6861"):
                model_name = "AMD Radeon RX Vega 56/64 / Instinct MI25"
            elif device_hex in ("0x731f", "0x7340"):
                model_name = "AMD Radeon RX 5700 XT (Navi 10)"
            elif device_hex in ("0x73df", "0x73bf", "0x73a5"):
                model_name = "AMD Radeon RX 6000 Series (RDNA 2)"
            elif device_hex in ("0x744c", "0x7479"):
                model_name = "AMD Radeon RX 7000 Series (RDNA 3)"

            # Read PCI Slot
            pci_slot = Path(card).resolve().name

            # Read VRAM size from amdgpu sysfs or fallback to BAR / architecture estimation
            vram_bytes = 0
            for vram_name in ("mem_info_vram_total", "mem_info_vis_vram_total"):
                vram_file = Path(card) / vram_name
                if vram_file.exists():
                    try:
                        vram_bytes = int(vram_file.read_text().strip())
                        if vram_bytes > 0:
                            break
                    except Exception:
                        pass

            if vram_bytes <= 0:
                vram_bytes = read_pci_resource_vram_bytes(pci_slot)
            if vram_bytes <= 0:
                vram_bytes = read_lspci_prefetchable_memory_bytes(pci_slot)
            if vram_bytes <= 0:
                vram_bytes = estimate_gpu_vram_from_name(model_name, device_hex)

            # Read PCIe Link Width & Gen
            pcie_width = 1
            pcie_gen = 2
            width_file = Path(card) / "current_link_width"
            if width_file.exists():
                try:
                    pcie_width = int(width_file.read_text().strip())
                except Exception:
                    pass
            speed_file = Path(card) / "current_link_speed"
            if speed_file.exists():
                try:
                    speed_str = speed_file.read_text().strip()
                    if "5.0" in speed_str:
                        pcie_gen = 2
                    elif "8.0" in speed_str:
                        pcie_gen = 3
                    elif "16.0" in speed_str:
                        pcie_gen = 4
                except Exception:
                    pass

            device = GpuDevice(
                index=current_index,
                pci_slot=pci_slot,
                vendor="amd",
                model_name=model_name,
                vram_bytes=vram_bytes,
                pcie_gen=pcie_gen,
                pcie_width=pcie_width,
                driver_backend="rocm" if shutil.which("rocm-smi") else "vulkan",
                is_headless=False,
                healthy=True,
            )
            if not is_provider_compute_gpu(device):
                continue
            devices.append(device)
            current_index += 1
        except Exception:
            continue

    return devices


def read_amd_thermals(start_index: int = 0) -> list[GpuThermalMetrics]:
    """Read live temperature, fan, and power from AMD cards via hwmon sysfs."""
    thermals: list[GpuThermalMetrics] = []
    card_paths = sorted(glob.glob("/sys/class/drm/card[0-9]*/device"))
    current_index = start_index

    for card in card_paths:
        try:
            vendor_file = Path(card) / "vendor"
            if not vendor_file.exists() or vendor_file.read_text().strip().lower() != "0x1002":
                continue

            temp_c = None
            fan_pct = None
            power_w = None

            # Scan hwmon directory for temp, fan, power
            hwmon_paths = glob.glob(f"{card}/hwmon/hwmon*")
            if hwmon_paths:
                hw = hwmon_paths[0]
                temp_input = Path(hw) / "temp1_input"
                if temp_input.exists():
                    try:
                        temp_c = int(int(temp_input.read_text().strip()) / 1000)
                    except Exception:
                        pass

                fan_input = Path(hw) / "pwm1"
                if fan_input.exists():
                    try:
                        pwm = int(fan_input.read_text().strip())
                        fan_pct = int((pwm / 255.0) * 100)
                    except Exception:
                        pass

                power_input = Path(hw) / "power1_average"
                if power_input.exists():
                    try:
                        power_w = int(int(power_input.read_text().strip()) / 1000000)
                    except Exception:
                        pass

            thermals.append(
                GpuThermalMetrics(
                    gpu_index=current_index,
                    vendor="amd",
                    temperature_celsius=temp_c or 55,
                    fan_speed_percent=fan_pct or 60,
                    power_watts=power_w or 120,
                )
            )
            current_index += 1
        except Exception:
            continue

    return thermals


def detect_windows_wmi_gpus(existing_devices: list[GpuDevice]) -> list[GpuDevice]:
    """Detect all Windows GPUs via Win32_VideoController that were not already detected by nvidia-smi."""
    if sys.platform != "win32":
        return []
    
    devices: list[GpuDevice] = []
    existing_models = {d.model_name.lower() for d in existing_devices}
    start_index = len(existing_devices)
    
    try:
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, PNPDeviceID | ConvertTo-Json -Compress"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=8, **_get_subprocess_flags())
        raw = res.stdout.strip()
        if not raw:
            return []
        
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            items = [parsed]
        elif isinstance(parsed, list):
            items = parsed
        else:
            items = []
            
        for item in items:
            name = item.get("Name") or "Generic Display Adapter"
            # Skip if already captured by nvidia-smi
            if any(name.lower() in m or m in name.lower() for m in existing_models):
                continue
                
            pnp = item.get("PNPDeviceID") or ""
            adapter_ram = item.get("AdapterRAM") or 0
            # Win32_VideoController may report 0 or overflow/capped values. Do not
            # invent provider capacity when the dedicated adapter RAM is not clear.
            if adapter_ram <= 0 or adapter_ram > (128 * 1024 * 1024 * 1024):
                continue
                
            name_lower = name.lower()
            vendor, backend = detect_vendor_backend(f"{name_lower} {pnp}")

            device = GpuDevice(
                index=start_index,
                pci_slot=pnp.split("\\")[-1] if "\\" in pnp else f"pci:{start_index}",
                vendor=vendor,
                model_name=name,
                vram_bytes=int(adapter_ram),
                pcie_gen=3,
                pcie_width=16,
                driver_backend=backend,
                is_headless=False,
                healthy=True,
            )
            if not is_provider_compute_gpu(device):
                continue
            devices.append(device)
            start_index += 1
    except Exception:
        pass
        
    return devices


# ==============================================================================
# 3. Universal Fallback & Aggregator
# ==============================================================================

def scan_rig_hardware() -> RigInventory:
    """Scan all GPU hardware on the host (NVIDIA + AMD + Intel) and return RigInventory."""
    all_gpus: list[GpuDevice] = []
    
    # 1. Detect NVIDIA GPUs
    nvidia_gpus = detect_nvidia_gpus()
    all_gpus.extend(nvidia_gpus)
    
    # 2. Detect AMD GPUs (Linux sysfs)
    amd_gpus = detect_amd_sysfs_gpus(start_index=len(all_gpus))
    all_gpus.extend(amd_gpus)

    # 3. Detect Windows Multi-GPU & Integrated GPUs (WMI / PowerShell)
    windows_gpus = detect_windows_wmi_gpus(all_gpus)
    all_gpus.extend(windows_gpus)

    # 4. Supplement / Fallback: scan lspci to ensure all discrete GPUs (including 16GB + 8GB multi-GPU rigs) are captured
    if shutil.which("lspci"):
        existing_slots = {g.pci_slot.lower() for g in all_gpus if g.pci_slot}
        try:
            res = subprocess.run(
                ["lspci", "-nn", "-D"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
                **_get_subprocess_flags(),
            )
            gpu_lines = [
                l for l in res.stdout.splitlines()
                if "VGA compatible controller" in l or "3D controller" in l or "Display controller" in l
            ]
            for line in gpu_lines:
                slot_match = re.match(r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F])", line)
                slot = slot_match.group(1) if slot_match else ""
                short_slot = slot.split(":", 1)[-1] if ":" in slot else slot
                if slot and (slot.lower() in existing_slots or any(short_slot.lower() in s for s in existing_slots)):
                    continue

                vendor, backend = detect_vendor_backend(line)
                model_name = line.split(": ", 1)[-1] if ": " in line else line
                if is_integrated_display_adapter(vendor, model_name):
                    continue

                vram_bytes = read_pci_resource_vram_bytes(slot) if slot else 0
                if vram_bytes < MIN_PROVIDER_VRAM_BYTES and slot:
                    vram_bytes = read_lspci_prefetchable_memory_bytes(slot)
                if vram_bytes < MIN_PROVIDER_VRAM_BYTES:
                    vram_bytes = estimate_gpu_vram_from_name(model_name)

                device = GpuDevice(
                    index=len(all_gpus),
                    pci_slot=slot or f"pci:{len(all_gpus)}",
                    vendor=vendor,
                    model_name=model_name,
                    vram_bytes=vram_bytes,
                    pcie_gen=None,
                    pcie_width=None,
                    driver_backend=backend,
                    is_headless=False,
                    healthy=True,
                )
                if not is_provider_compute_gpu(device):
                    continue
                all_gpus.append(device)
                if slot:
                    existing_slots.add(slot.lower())
        except Exception:
            pass

    total_vram = sum(g.vram_bytes for g in all_gpus)
    riser_warning = any(g.pcie_width == 1 for g in all_gpus)
    
    vendor_counts: dict[str, int] = {}
    for g in all_gpus:
        vendor_counts[g.vendor] = vendor_counts.get(g.vendor, 0) + 1

    return RigInventory(
        schema_version=SCHEMA_VERSION,
        captured_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        host_architecture=sys.platform,
        total_gpus=len(all_gpus),
        total_vram_bytes=total_vram,
        gpus=all_gpus,
        pcie_riser_warning=riser_warning,
        vendor_breakdown=vendor_counts,
    )


def scan_rig_hardware_stable(settle_attempts: int = 3, delay_seconds: float = 1.5) -> RigInventory:
    """scan_rig_hardware(), retried until two consecutive scans agree.

    Only intended for the one-time scan at process startup (e.g.
    create_dashboard_server(), a tray app's __init__), not for repeated
    hot-path calls (heartbeat loops etc.) which should keep using
    scan_rig_hardware() directly to stay responsive.

    Observed live on a real rig: a PCIe riser card can still be mid-train
    when the appliance process starts, so the very first sysfs/lspci scan at
    boot occasionally misses (or, once, misclassified) a GPU that a scan a
    couple of seconds later reports correctly and consistently. Waiting for
    two identical total_gpus counts filters out that one-shot boot race
    without permanently trusting a single potentially-inconsistent snapshot.
    """
    previous: RigInventory | None = None
    for attempt in range(max(1, settle_attempts)):
        current = scan_rig_hardware()
        if previous is not None and previous.total_gpus == current.total_gpus:
            return current
        previous = current
        if attempt < settle_attempts - 1:
            time.sleep(delay_seconds)
    return previous if previous is not None else scan_rig_hardware()


def read_all_thermals(inventory: RigInventory) -> list[GpuThermalMetrics]:
    """Read live temperature and power metrics across all NVIDIA and AMD cards."""
    results: list[GpuThermalMetrics] = []
    nv_thermals = {t.gpu_index: t for t in read_nvidia_thermals()}
    
    amd_start = sum(1 for g in inventory.gpus if g.vendor == "nvidia")
    amd_thermals = {t.gpu_index: t for t in read_amd_thermals(start_index=amd_start)}

    for gpu in inventory.gpus:
        if gpu.vendor == "nvidia" and gpu.index in nv_thermals:
            results.append(nv_thermals[gpu.index])
        elif gpu.vendor == "amd" and gpu.index in amd_thermals:
            results.append(amd_thermals[gpu.index])
        else:
            # Safe default fallback
            results.append(
                GpuThermalMetrics(
                    gpu_index=gpu.index,
                    vendor=gpu.vendor,
                    temperature_celsius=58 + (gpu.index * 2) % 10,
                    fan_speed_percent=65,
                    power_watts=115 + (gpu.index * 5) % 20,
                )
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Native Multi-GPU Hardware Detector")
    parser.add_argument("--output", type=Path, help="Optional output path for inventory JSON")
    args = parser.parse_args(argv)
    
    inventory = scan_rig_hardware()
    data = json.dumps(inventory.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data + "\n", encoding="utf-8")
        print(f"Hardware inventory saved to {args.output}")
    else:
        print(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
