"""Idle cost and leak check of the real Shell in --test-mode (windows rendered but parked off-screen; no taskbar or
work-area changes, no input). Measures:

* idle CPU and memory after start-up settles;
* handles, GDI/USER objects and memory before and after many power off/on cycles and preview data refreshes;
* idle CPU again afterwards.

    .venv\\Scripts\\python tools\\perf\\shell_soak.py [--cycles 25] [--idle 20] [--out docs\\perf\\shell_soak.json]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32")
psapi = ctypes.WinDLL("psapi")
k32.OpenProcess.restype = wintypes.HANDLE
k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
k32.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
u32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
               [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                               "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]


def shell_pid(launcher_pid: int) -> int:
    """The venv's python.exe is a launcher; the Shell is its child."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={launcher_pid}').ProcessId"],
                         capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else launcher_pid


def sample(pid: int) -> dict:
    h = k32.OpenProcess(0x0400 | 0x0010, False, pid)
    c, e, k, u = (wintypes.FILETIME() for _ in range(4))
    k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    cpu = ((k.dwHighDateTime << 32 | k.dwLowDateTime) + (u.dwHighDateTime << 32 | u.dwLowDateTime)) / 1e7
    hc = wintypes.DWORD()
    k32.GetProcessHandleCount(h, ctypes.byref(hc))
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    out = {"cpu_s": cpu, "handles": hc.value, "gdi": u32.GetGuiResources(h, 0), "user": u32.GetGuiResources(h, 1),
           "private_mb": round(pmc.PrivateUsage / 2**20, 1), "working_set_mb": round(pmc.WorkingSetSize / 2**20, 1)}
    k32.CloseHandle(h)
    return out


def idle_cpu(pid: int, seconds: float) -> float:
    a = sample(pid)["cpu_s"]
    time.sleep(seconds)
    return round((sample(pid)["cpu_s"] - a) / seconds * 100, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=25)
    ap.add_argument("--idle", type=float, default=20)
    ap.add_argument("--out", default=str(ROOT / "docs" / "perf" / "shell_soak.json"))
    args = ap.parse_args()
    data = Path(tempfile.mkdtemp(prefix="glass-soak-"))
    suffix = "soak" + uuid.uuid4().hex[:6]
    os.environ.update(GLASS_DATA_DIR=str(data), GLASS_PIPE_SUFFIX=suffix)
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
    proc = subprocess.Popen([sys.executable, "-m", "glass.shell", "--test-mode", "--no-watchdog"], cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=open(data / "stderr.txt", "wb"))
    from glass.core.pipeclient import PipeClient
    deadline = time.time() + 60
    while True:
        try:
            c = PipeClient("Shell", timeout=2).__enter__()
            break
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(0.5)
    pid = shell_pid(proc.pid)
    time.sleep(10)                                   # let start-up work (icons, weather, catalog) settle
    report = {"pid": pid, "start": sample(pid), "idle_cpu_percent_one_core": idle_cpu(pid, args.idle)}
    before = sample(pid)
    t0 = time.time()
    for _ in range(args.cycles):
        c.call("shell.command", {"command": "power_off"})
        c.call("shell.command", {"command": "power_on"})
        c.call("dock.apps")
        c.call("markets.get")
    report["cycle_seconds_each"] = round((time.time() - t0) / args.cycles, 3)
    time.sleep(8)
    after = sample(pid)
    report.update(before_cycles=before, after_cycles=after, cycles=args.cycles,
                  growth={k: round(after[k] - before[k], 1) for k in ("handles", "gdi", "user", "private_mb")},
                  idle_cpu_after_percent_one_core=idle_cpu(pid, args.idle))
    c.call("shell.command", {"command": "quit"})
    c.__exit__(None, None, None)
    proc.wait(30)
    report["stderr_tracebacks"] = (data / "stderr.txt").read_text(encoding="utf-8", errors="replace").count("Traceback")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
