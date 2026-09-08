"""Privacy-preserving stable machine fingerprint for ComputeMesh provider inventory.

The fingerprint supplements — never replaces — the Ed25519 node identity. Raw
serials, MAC addresses and processor identifiers stay local; only the SHA-256
fingerprint and the names of contributing source classes are transmitted.

Identity sources are selected by stability tier. Firmware/chassis identifiers win;
OS machine-id, processor-id and MAC are fallbacks. This avoids changing a machine ID
merely because a NIC is added or replaced when stronger hardware identity exists.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import uuid
from typing import Callable

IDENTITY_VERSION = 1
_MACHINE_ID_PREFIX = f"hw{IDENTITY_VERSION}:"
_PLACEHOLDERS = {
    "", "none", "unknown", "not specified", "not applicable", "default string",
    "to be filled by o.e.m.", "system serial number", "00000000-0000-0000-0000-000000000000",
}
_FIRMWARE_UUID_SOURCES = ("dmi_product_uuid", "system_uuid", "platform_uuid")
_CHASSIS_SERIAL_SOURCES = (
    "dmi_board_serial", "dmi_product_serial", "board_serial", "platform_serial"
)


class MachineIdentityError(RuntimeError):
    pass


@dataclass(frozen=True)
class MachineIdentity:
    machine_id: str
    identity_version: int
    sources: tuple[str, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "machine_id": self.machine_id,
            "identity_version": self.identity_version,
            "sources": list(self.sources),
        }


def _normal(value: str | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(str(value).strip().split()).lower()
    if compact in _PLACEHOLDERS or not compact:
        return None
    return compact[:512]


def _read(path: str) -> str | None:
    try:
        return _normal(Path(path).read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError):
        return None


def _run(command: list[str], *, timeout: float = 2.0) -> str | None:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _normal(result.stdout)


def _linux_signals() -> dict[str, str]:
    mapping = {
        "dmi_product_uuid": "/sys/class/dmi/id/product_uuid",
        "dmi_board_serial": "/sys/class/dmi/id/board_serial",
        "dmi_product_serial": "/sys/class/dmi/id/product_serial",
        "machine_id": "/etc/machine-id",
    }
    return {name: value for name, path in mapping.items() if (value := _read(path)) is not None}


def _windows_signals() -> dict[str, str]:
    if os.name != "nt":
        return {}
    powershell = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    commands = {
        "system_uuid": "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
        "board_serial": "(Get-CimInstance Win32_BaseBoard).SerialNumber",
        "processor_id": "(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId",
    }
    result: dict[str, str] = {}
    for name, script in commands.items():
        value = _run(powershell + [script])
        if value is not None:
            result[name] = value
    return result


def _darwin_signals() -> dict[str, str]:
    if platform.system() != "Darwin":
        return {}
    raw = _run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
    if not raw:
        return {}
    result: dict[str, str] = {}
    for source, key in (("platform_uuid", "IOPlatformUUID"), ("platform_serial", "IOPlatformSerialNumber")):
        match = re.search(rf'"{key}"\s*=\s*"([^"]+)"', raw, re.IGNORECASE)
        if match and (value := _normal(match.group(1))):
            result[source] = value
    return result


def _portable_signals() -> dict[str, str]:
    result: dict[str, str] = {}
    mac = uuid.getnode()
    # uuid.getnode() marks generated fallbacks with the multicast bit. Such values
    # are implementation fallbacks, not a trustworthy durable NIC ID.
    if isinstance(mac, int) and 0 < mac < (1 << 48) and not (mac & (1 << 40)):
        result["mac"] = f"{mac:012x}"
    processor = _normal(platform.processor())
    if processor:
        result["processor_model"] = processor
    architecture = _normal(platform.machine())
    if architecture:
        result["architecture"] = architecture
    return result


def _select_identity_signals(signals: dict[str, str]) -> dict[str, str]:
    """Choose the most stable available identity tier, excluding descriptive CPU data."""
    firmware = {name: signals[name] for name in _FIRMWARE_UUID_SOURCES if name in signals}
    serials = {name: signals[name] for name in _CHASSIS_SERIAL_SOURCES if name in signals}
    if firmware:
        # Board/chassis serials may strengthen a firmware UUID but MAC/CPU changes
        # must not re-identify an otherwise stable machine.
        return {**firmware, **serials}
    if serials:
        return serials
    if "machine_id" in signals:
        return {"machine_id": signals["machine_id"]}
    if "processor_id" in signals:
        return {"processor_id": signals["processor_id"]}
    if "mac" in signals:
        return {"mac": signals["mac"]}
    raise MachineIdentityError("no stable host-specific machine identity source is available")


def collect_machine_identity(*, signal_provider: Callable[[], dict[str, str]] | None = None) -> MachineIdentity:
    if signal_provider is not None:
        raw = signal_provider()
    else:
        system = platform.system()
        raw: dict[str, str] = {}
        if system == "Linux":
            raw.update(_linux_signals())
        elif system == "Windows":
            raw.update(_windows_signals())
        elif system == "Darwin":
            raw.update(_darwin_signals())
        raw.update(_portable_signals())

    signals = {
        str(name): value
        for name, raw_value in raw.items()
        if (value := _normal(raw_value)) is not None
    }
    selected = _select_identity_signals(signals)
    canonical = json.dumps(
        {"version": IDENTITY_VERSION, "signals": selected},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    digest = hashlib.sha256(canonical).hexdigest()
    return MachineIdentity(
        machine_id=_MACHINE_ID_PREFIX + digest,
        identity_version=IDENTITY_VERSION,
        sources=tuple(sorted(selected)),
    )


def attach_governance_identity(
    profile: dict[str, object],
    *,
    fleet_id: str,
    identity: MachineIdentity | None = None,
) -> dict[str, object]:
    """Return a copy of a node profile with validated fleet and hardware metadata."""
    fleet_id = str(fleet_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", fleet_id):
        raise MachineIdentityError("fleet_id is invalid")
    identity = identity or collect_machine_identity()
    result = dict(profile)
    result["fleet_id"] = fleet_id
    result["machine_identity"] = identity.to_public_dict()
    return result
