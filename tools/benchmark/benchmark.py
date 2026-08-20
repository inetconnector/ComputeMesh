#!/usr/bin/env python3
"""Minimal M0 ComputeMesh node inventory benchmark harness.

The collector deliberately uses only the Python standard library. It emits a
node-profile document and an inventory benchmark result that match the current
M0 semantic contracts. It is not a performance benchmark yet.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def memory_bytes() -> tuple[int, int]:
    """Return (total, available) physical memory without third-party packages."""
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0, 0
        return int(status.ullTotalPhys), int(status.ullAvailPhys)

    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total_pages = int(os.sysconf("SC_PHYS_PAGES"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        return page_size * total_pages, page_size * available_pages
    except (AttributeError, OSError, ValueError):
        return 0, 0


def parse_nvidia_smi(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for index, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        name, memory_mib, driver_version = parts
        try:
            memory_total_bytes = int(float(memory_mib) * 1024 * 1024)
        except ValueError:
            memory_total_bytes = 0
        devices.append(
            {
                "device_id": f"gpu:{index}",
                "kind": "gpu",
                "vendor": "NVIDIA",
                "name": name,
                "memory_total_bytes": memory_total_bytes,
                "driver_version": driver_version,
                "backend": "cuda",
            }
        )
    return devices


def detect_nvidia_devices() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_nvidia_smi(completed.stdout)


def collect_node_profile(node_id: str, profile_revision: int) -> dict[str, Any]:
    total_memory, available_memory = memory_bytes()
    cpu_model = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "")
    return {
        "schema_version": SCHEMA_VERSION,
        "node_id": node_id,
        "profile_revision": profile_revision,
        "captured_at": utc_now(),
        "platform": {
            "os": platform.system() or sys.platform,
            "release": platform.release(),
            "architecture": platform.machine() or "unknown",
            "python_version": platform.python_version(),
        },
        "cpu": {
            "model": cpu_model,
            "logical_cores": max(1, os.cpu_count() or 1),
        },
        "memory": {
            "total_bytes": max(0, total_memory),
            "available_bytes": max(0, available_memory),
        },
        "devices": detect_nvidia_devices(),
        "runtime_capabilities": [],
        "provider_limits": {
            "draining": False,
            "max_memory_fraction": 0.90,
            "max_power_watts": None,
        },
        "benchmark_refs": [],
    }


def collect_inventory_benchmark(profile_revision: int, elapsed_ms: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "benchmark_name": "inventory_capture",
        "captured_at": utc_now(),
        "profile_revision": profile_revision,
        "conditions": {
            "warm_state": "not_applicable",
            "notes": "M0 standard-library inventory collector",
        },
        "metrics": {
            "collector_elapsed_ms": round(elapsed_ms, 3),
        },
        "raw_samples": [],
    }


def validate_semantic_minimum(profile: dict[str, Any], result: dict[str, Any]) -> None:
    """Fail fast on collector bugs without pretending to be a JSON Schema engine."""
    required_profile = {
        "schema_version",
        "node_id",
        "profile_revision",
        "captured_at",
        "platform",
        "cpu",
        "memory",
        "devices",
        "runtime_capabilities",
        "provider_limits",
        "benchmark_refs",
    }
    required_result = {
        "schema_version",
        "run_id",
        "benchmark_name",
        "captured_at",
        "profile_revision",
        "conditions",
        "metrics",
        "raw_samples",
    }
    if set(profile) != required_profile:
        raise ValueError(f"node profile keys differ from contract: {sorted(set(profile) ^ required_profile)}")
    if set(result) != required_result:
        raise ValueError(f"benchmark result keys differ from contract: {sorted(set(result) ^ required_result)}")
    if profile["schema_version"] != SCHEMA_VERSION or result["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema version")
    if profile["profile_revision"] != result["profile_revision"]:
        raise ValueError("profile revision mismatch")
    if profile["memory"]["available_bytes"] < 0 or profile["memory"]["total_bytes"] < 0:
        raise ValueError("negative memory value")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect an M0 ComputeMesh node inventory profile")
    parser.add_argument("--node-id", default="unenrolled", help="Stable node id when enrollment exists")
    parser.add_argument("--profile-revision", type=int, default=0)
    parser.add_argument("--output-dir", default="artifacts/benchmark")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON instead of writing files")
    args = parser.parse_args(argv)

    if args.profile_revision < 0:
        parser.error("--profile-revision must be >= 0")

    started = time.perf_counter()
    profile = collect_node_profile(args.node_id, args.profile_revision)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = collect_inventory_benchmark(args.profile_revision, elapsed_ms)
    profile["benchmark_refs"] = [result["run_id"]]
    validate_semantic_minimum(profile, result)

    if args.dry_run:
        print(json.dumps({"node_profile": profile, "benchmark_result": result}, indent=2, sort_keys=True))
        return 0

    output_dir = Path(args.output_dir)
    write_json(output_dir / "node_profile.json", profile)
    write_json(output_dir / f"benchmark_{result['run_id']}.json", result)
    print(output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
