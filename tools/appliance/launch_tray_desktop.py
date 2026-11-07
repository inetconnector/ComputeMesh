#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Direct WinSta0\\Default Interactive Desktop Launcher for ComputeMesh System Tray."""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_char_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def launch_on_default_desktop() -> int:
    if sys.platform != "win32":
        print("[!] Supported only on Windows.")
        return 1

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(STARTUPINFO)
    si.lpDesktop = "WinSta0\\Default"
    pi = PROCESS_INFORMATION()

    py_exe = Path(sys.executable).parent / "pythonw.exe"
    if not py_exe.exists():
        py_exe = Path(sys.executable)

    target_script = REPO_ROOT / "tools" / "appliance" / "windows_tray_app.py"
    cmd_line = f'"{py_exe}" "{target_script}"'

    k32 = ctypes.windll.kernel32
    res = k32.CreateProcessW(
        None,
        cmd_line,
        None,
        None,
        False,
        0,
        None,
        str(REPO_ROOT),
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if res:
        print(f"[*] ComputeMesh Tray App successfully launched on WinSta0\\Default (PID {pi.dwProcessId}).")
        k32.CloseHandle(pi.hProcess)
        k32.CloseHandle(pi.hThread)
        return 0
    else:
        err = k32.GetLastError()
        print(f"[!] CreateProcess failed with error code {err}")
        return 1


if __name__ == "__main__":
    sys.exit(launch_on_default_desktop())
