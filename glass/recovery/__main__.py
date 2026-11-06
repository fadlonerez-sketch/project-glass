from __future__ import annotations

import argparse
import ctypes
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from glass.core import paths
from glass.win import shellbar
from glass.win.winapi import process_image

log = logging.getLogger("glass.recovery")
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
user32.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL,
                                             wintypes.DWORD, wintypes.DWORD]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]

SYNCHRONIZE = 0x00100000
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
RECOVERY_HOTKEY = "Ctrl+Alt+Shift+R"
CRASH_LOG = "crashes.json"


def setup_logging() -> None:
    h = logging.handlers.RotatingFileHandler(paths.logs_dir() / "recovery.log", maxBytes=500_000, backupCount=2,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)


def _pythonw() -> str:
    exe = Path(sys.executable)
    return str(exe.parent / "pythonw.exe") if (exe.parent / "pythonw.exe").exists() else str(exe)


def is_glass_process(pid: int) -> bool:
    image = process_image(pid).lower()
    return image.endswith(("python.exe", "pythonw.exe"))


def stop_process(pid: int) -> bool:
    if not pid or not is_glass_process(pid):
        return False
    h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    try:
        return bool(kernel32.TerminateProcess(h, 3))
    finally:
        kernel32.CloseHandle(h)


def notify_work_area_changed() -> None:
    """Ask Windows to recompute the desktop work area once Glass's app bars are gone."""
    SPI_SETWORKAREA = 0x002F
    user32.SystemParametersInfoW(SPI_SETWORKAREA, 0, None, 0x2)


def restore(stop_shell: bool = True) -> dict:
    state_path = paths.state_file()
    st = shellbar.read_state(state_path)
    result = {"taskbar_restored": False, "shell_stopped": False}
    pid = int(st.get("shell_pid") or 0)
    if stop_shell and pid and pid != os.getpid():
        # Ask the Shell to quit by itself first (it unregisters its app bars and restores the taskbar);
        # only stop the process if it doesn't answer.
        try:
            from glass.core.pipeclient import PipeClient
            with PipeClient("Shell", timeout=2.0) as c:
                c.call("shell.command", {"command": "quit"})
            for _ in range(40):
                if not process_image(pid):
                    break
                time.sleep(0.1)
        except Exception as exc:  # not running, hung, or no token
            log.info("graceful quit not possible: %s", exc)
        if process_image(pid):
            result["shell_stopped"] = stop_process(pid)
        else:
            result["shell_stopped"] = True
    result["taskbar_restored"] = shellbar.restore_taskbar_from_state(state_path)
    notify_work_area_changed()
    st = shellbar.read_state(state_path)
    st.update(clean_exit=True, user_restored=time.time())
    shellbar.write_state(state_path, st)
    log.info("restore: %s", result)
    return result


def _recent_crashes(now: float) -> list[float]:
    path = paths.data_dir() / CRASH_LOG
    try:
        crashes = [float(t) for t in json.loads(path.read_text())]
    except (OSError, ValueError):
        crashes = []
    crashes = [t for t in crashes if now - t < 600] + [now]
    path.write_text(json.dumps(crashes))
    return crashes


def watch(pid: int) -> int:
    handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        log.error("cannot watch pid %d", pid)
        return 1
    hotkeys = shellbar.GlobalHotkeys()
    user_requested = {"flag": False}

    def on_hotkey():
        log.info("recovery hotkey pressed")
        user_requested["flag"] = True
        restore(stop_shell=True)

    hotkeys.register(RECOVERY_HOTKEY, on_hotkey)
    msg = wintypes.MSG()
    handles = (wintypes.HANDLE * 1)(handle)
    try:
        while True:
            rc = user32.MsgWaitForMultipleObjects(1, handles, False, 0xFFFFFFFF, 0x04FF)  # QS_ALLINPUT
            if rc == 0:
                break  # the Shell exited
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                hotkeys.handle(msg.message, msg.wParam)
    finally:
        hotkeys.unregister_all()
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    st = shellbar.read_state(paths.state_file())
    if st.get("clean_exit") or user_requested["flag"]:
        log.info("Shell exited cleanly (code %d)", code.value)
        if st.get("taskbar_hidden"):
            shellbar.restore_taskbar_from_state(paths.state_file())
        return 0
    log.error("Shell exited unexpectedly (code %d); restoring the Windows taskbar", code.value)
    shellbar.restore_taskbar_from_state(paths.state_file())
    notify_work_area_changed()
    crashes = _recent_crashes(time.time())
    if len(crashes) <= 3:
        log.info("restarting the Shell (crash %d in 10 min)", len(crashes))
        time.sleep(2)
        subprocess.Popen([_pythonw(), "-m", "glass.shell"], cwd=str(paths.PROJECT_DIR),
                         creationflags=subprocess.DETACHED_PROCESS)
    else:
        log.error("the Shell crashed %d times in 10 minutes; leaving the standard Windows desktop", len(crashes))
        user32.MessageBoxW(None, "Project Glass stopped unexpectedly several times, so the standard Windows "
                                 "desktop has been restored.\n\nLogs: " + str(paths.logs_dir()),
                           "Project Glass", 0x40 | 0x40000)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="glass.recovery")
    ap.add_argument("--watch", type=int, default=0)
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args(argv)
    setup_logging()
    if args.restore:
        print(json.dumps(restore(stop_shell=True)))
        return 0
    if args.watch:
        return watch(args.watch)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
