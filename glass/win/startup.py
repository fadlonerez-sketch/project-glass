"""Start with Windows: one value under HKCU\\...\\Run (off by default, removed again when turned off).

The command is the project's own pythonw.exe with ``-m glass.shell``; the installer puts a .pth file in
the virtual environment so the package imports from any working directory (no script hosts involved).
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "ProjectGlass"


def command() -> str:
    exe = Path(sys.executable)
    pyw = exe.parent / "pythonw.exe"
    return f'"{pyw if pyw.exists() else exe}" -m glass.shell'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass
