"""Safe, capability-aware GPU fan control for provider appliances.

Fan control is vendor and driver specific. This module never reports a
synthetic capability and never falls back to a guessed fan percentage.
Automatic driver control remains the safe default; manual control is exposed
only for Linux amdgpu PWM devices or an explicitly available nvidia-settings
backend.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import glob
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.appliance.hardware_detector import RigInventory


@dataclass(frozen=True)
class FanGpuCapability:
    gpu_index: int
    vendor: str
    mode: str
    manual_control: bool
    auto_control: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _flags() -> dict[str, Any]:
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None


def _amd_hwmon_paths() -> list[Path]:
    return [Path(p) for p in sorted(glob.glob("/sys/class/drm/card[0-9]*/device/hwmon/hwmon*"))]


def _amd_hwmon_for_index(gpu_index: int, inventory: RigInventory | None = None) -> Path | None:
    paths = _amd_hwmon_paths()
    if inventory is not None:
        amd_indexes = [gpu.index for gpu in inventory.gpus if str(gpu.vendor).lower() == "amd"]
        try:
            ordinal = amd_indexes.index(gpu_index)
        except ValueError:
            return None
    else:
        ordinal = gpu_index
    if 0 <= ordinal < len(paths):
        return paths[ordinal]
    return None


def get_fan_capabilities(inventory: RigInventory) -> list[FanGpuCapability]:
    """Return actual per-GPU control support without making hardware changes."""
    nvidia_settings = _command_available("nvidia-settings")
    amd_sysfs = sys.platform != "win32" and bool(_amd_hwmon_paths())
    capabilities: list[FanGpuCapability] = []
    for gpu in inventory.gpus:
        if gpu.vendor == "amd":
            hw = _amd_hwmon_for_index(gpu.index, inventory)
            pwm = hw / "pwm1" if hw else None
            if amd_sysfs and pwm and pwm.exists() and os.access(pwm, os.W_OK):
                reason = "amdgpu PWM"
                manual = True
            else:
                reason = "AMD-Treiber stellt keine beschreibbare PWM-Schnittstelle bereit"
                manual = False
        elif gpu.vendor == "nvidia" and nvidia_settings and sys.platform != "win32":
            reason = "nvidia-settings"
            manual = True
        else:
            reason = "GPU-Treiber stellt keine sichere manuelle Lüftersteuerung bereit"
            manual = False
        capabilities.append(
            FanGpuCapability(
                gpu_index=gpu.index,
                vendor=gpu.vendor,
                mode="auto",
                manual_control=manual,
                auto_control=True,
                reason=reason,
            )
        )
    return capabilities


def fan_status(inventory: RigInventory, config: Any) -> dict[str, Any]:
    capabilities = get_fan_capabilities(inventory)
    manual = any(item.manual_control for item in capabilities)
    mode = str(getattr(config, "fan_control_mode", "safe_auto") or "safe_auto")
    target = int(getattr(config, "fan_target_percent", 60) or 60)
    selected_mode = mode if mode in {"auto", "safe_auto", "manual"} else "safe_auto"
    if manual:
        message = (
            "Sicherer Lüftermodus aktiv: mindestens 25 %, bei steigender Temperatur automatisch mehr."
            if selected_mode == "safe_auto"
            else "Lüftersteuerung verfügbar; das ausgewählte Profil wird beim Anwenden geprüft."
        )
    else:
        message = (
            "Nur automatische Treibersteuerung verfügbar; eine Mindestdrehzahl kann der "
            "installierte GPU-Treiber nicht erzwingen."
        )
    return {
        "mode": selected_mode,
        "target_percent": max(20, min(100, target)),
        "control_available": manual,
        "supported_modes": ["safe_auto", "auto", "manual"] if manual else ["safe_auto", "auto"],
        "gpus": [item.to_dict() for item in capabilities],
        "message": message,
    }


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="ascii")


def _apply_amd_sysfs(gpu_index: int, mode: str, target: int, inventory: RigInventory | None = None) -> tuple[bool, str]:
    hw = _amd_hwmon_for_index(gpu_index, inventory)
    if hw is None:
        return False, "AMD-PWM-Schnittstelle nicht gefunden"
    pwm = hw / "pwm1"
    enable = hw / "pwm1_enable"
    if not pwm.exists() or not os.access(pwm, os.W_OK):
        return False, "AMD-PWM-Schnittstelle ist nicht beschreibbar"
    try:
        if mode == "auto":
            if enable.exists() and os.access(enable, os.W_OK):
                _write_text(enable, "2")
            return True, "Treiber-Automatik aktiviert"
        if enable.exists() and os.access(enable, os.W_OK):
            _write_text(enable, "1")
        _write_text(pwm, str(round(target * 255 / 100)))
        return True, f"PWM auf {target}% gesetzt"
    except OSError as exc:
        return False, f"PWM konnte nicht gesetzt werden: {exc}"


def _apply_nvidia_settings(gpu_index: int, mode: str, target: int) -> tuple[bool, str]:
    if not _command_available("nvidia-settings"):
        return False, "nvidia-settings ist nicht installiert"
    if sys.platform == "win32":
        return False, "nvidia-settings ist unter Windows nicht verfügbar"
    try:
        display = os.environ.get("DISPLAY", ":0")
        values = [f"[gpu:{gpu_index}]/GPUFanControlState={'0' if mode == 'auto' else '1'}"]
        if mode in {"manual", "safe_auto"}:
            values.append(f"[gpu:{gpu_index}]/GPUTargetFanSpeed={target}")
        command = ["nvidia-settings", "-c", display]
        for value in values:
            command.extend(["-a", value])
        result = subprocess.run(command, capture_output=True, text=True, timeout=8, **_flags())
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "nvidia-settings fehlgeschlagen").strip()[-300:]
        return True, "NVIDIA-Lüfterprofil angewendet"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"NVIDIA-Lüfterprofil fehlgeschlagen: {exc}"


def _safe_curve_target(temperature: int | None, minimum: int) -> int:
    if temperature is None:
        return minimum
    if temperature >= 80:
        return 100
    if temperature >= 72:
        return max(minimum, 80)
    if temperature >= 62:
        return max(minimum, 55)
    if temperature >= 50:
        return max(minimum, 40)
    return minimum


def apply_fan_policy(inventory: RigInventory, mode: str, target_percent: int) -> dict[str, Any]:
    """Apply a validated fan profile and return per-GPU results."""
    mode = str(mode or "auto").strip().lower()
    if mode not in {"auto", "safe_auto", "manual"}:
        raise ValueError("fan_control_mode must be 'auto', 'safe_auto' or 'manual'")
    target = int(target_percent)
    if not 20 <= target <= 100:
        raise ValueError("fan_target_percent must be between 20 and 100")
    temperatures: dict[int, int | None] = {}
    if mode == "safe_auto":
        try:
            from tools.appliance.hardware_detector import read_all_thermals
            temperatures = {item.gpu_index: item.temperature_celsius for item in read_all_thermals(inventory)}
        except Exception:
            temperatures = {}
    results: list[dict[str, Any]] = []
    for gpu in inventory.gpus:
        effective_target = _safe_curve_target(temperatures.get(gpu.index), target_percent) if mode == "safe_auto" else target
        effective_mode = "manual" if mode == "safe_auto" else mode
        if gpu.vendor == "amd":
            applied, message = _apply_amd_sysfs(gpu.index, effective_mode, effective_target, inventory)
        elif gpu.vendor == "nvidia":
            applied, message = _apply_nvidia_settings(gpu.index, effective_mode, effective_target)
        else:
            applied, message = False, "GPU-Hersteller wird nicht unterstützt"
        results.append({"gpu_index": gpu.index, "applied": applied, "target_percent": effective_target, "message": message})
    applied_count = sum(1 for item in results if item["applied"])
    return {
        "mode": mode,
        "target_percent": target,
        "applied": applied_count > 0 or not inventory.gpus,
        "applied_count": applied_count,
        "results": results,
    }


class FanSafetyController:
    """Keep a supported Linux GPU fan above the zero-RPM danger state."""

    def __init__(self, inventory: RigInventory, config: Any, interval_seconds: float = 5.0) -> None:
        self.inventory = inventory
        self.config = config
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: Any = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="computemesh-fan-safety", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                mode = str(getattr(self.config, "fan_control_mode", "safe_auto") or "safe_auto")
                if mode == "safe_auto":
                    apply_fan_policy(self.inventory, "safe_auto", 25)
            except Exception:
                pass
            self._stop.wait(self.interval_seconds)
