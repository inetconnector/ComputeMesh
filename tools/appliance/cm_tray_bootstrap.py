"""Initialize frozen and direct-script Windows tray environment before GUI imports."""
from __future__ import annotations

import io
import multiprocessing
import os
import sys
from pathlib import Path

# Ensure PyInstaller Windows child process bootloader compatibility
multiprocessing.freeze_support()

# Sanitize PyInstaller child process environment variables to prevent bootloader security check errors
for _pyi_env in list(os.environ.keys()):
    if _pyi_env.startswith(("_MEI", "_PYI", "PYINSTALLER")):
        os.environ.pop(_pyi_env, None)

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

if getattr(sys, "frozen", False):
    REPO_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # Ensure Tcl/Tk data directories are found in frozen environments
    for _tcl_cand in [REPO_ROOT / "_tcl_data", REPO_ROOT / "tcl" / "tcl8.6", REPO_ROOT / "tcl"]:
        if _tcl_cand.exists() and (_tcl_cand / "init.tcl").exists():
            os.environ["TCL_LIBRARY"] = str(_tcl_cand)
            break
    for _tk_cand in [REPO_ROOT / "_tk_data", REPO_ROOT / "tcl" / "tk8.6", REPO_ROOT / "tk"]:
        if _tk_cand.exists() and (_tk_cand / "tk.tcl").exists():
            os.environ["TK_LIBRARY"] = str(_tk_cand)
            break
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def ensure_interactive_desktop() -> None:
    """Ensure process and thread are attached to the interactive desktop (WinSta0\\Default).

    In automated shells, CI, or sandboxed environments, processes may be spawned
    in an isolated window station/desktop where no Windows Explorer taskbar exists.
    Switching to WinSta0\\Default ensures the system tray icon appears on the user's
    real, visible taskbar.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        h_winsta = user32.OpenWindowStationW("WinSta0", False, 0x037F)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta)
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


ensure_interactive_desktop()

if sys.platform == "win32":
    import threading
    _orig_thread_run = threading.Thread.run

    def _bootstrap_thread_run(self, *args, **kwargs):
        ensure_interactive_desktop()
        return _orig_thread_run(self, *args, **kwargs)

    threading.Thread.run = _bootstrap_thread_run
