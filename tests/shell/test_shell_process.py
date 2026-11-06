"""The real Glass.Shell process end to end, in --test-mode (windows rendered but parked off-screen; no space
reservation, taskbar change or hotkeys), with its own data folder and pipe names.

Covers: startup with the real services, the automation engine it supervises, the Shell API the Control
Center uses (settings round trip, theme, status, dock, catalog), and a clean, recorded shutdown.
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from glass.core.pipeclient import PipeClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def shell(tmp_path, monkeypatch):
    data = tmp_path / "glass"
    suffix = "t" + uuid.uuid4().hex[:8]
    monkeypatch.setenv("GLASS_DATA_DIR", str(data))
    monkeypatch.setenv("GLASS_PIPE_SUFFIX", suffix)
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
    env.update(GLASS_DATA_DIR=str(data), GLASS_PIPE_SUFFIX=suffix, LAUNCHDECK_DATA_DIR=str(tmp_path / "ld"))
    errlog = open(tmp_path / "shell-stderr.txt", "wb")   # a file, never a pipe: a full pipe would block the Shell
    proc = subprocess.Popen([sys.executable, "-m", "glass.shell", "--test-mode", "--no-watchdog"], cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=errlog)
    proc.errlog = tmp_path / "shell-stderr.txt"
    yield proc, data
    errlog.close()
    if proc.poll() is None:
        proc.kill()
        proc.wait(10)


def connect(timeout=45.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            return PipeClient("Shell", timeout=2).__enter__()
        except Exception as exc:  # not up yet / token not written yet
            last = exc
            time.sleep(0.4)
    raise AssertionError(f"Shell API never came up: {last}")


def test_shell_runs_serves_the_control_center_api_and_quits_cleanly(shell):
    proc, data = shell
    c = connect()
    try:
        status = c.call("status.get")
        assert status["version"] and status["screens"] and status["taskbar_hidden"] is False and status["appbars"] == 0

        res = c.call("settings.patch", {"values": {"glass.intensity": 0.4, "glass.blur": 2.0}})
        assert res["changed"] == {"glass.intensity": 0.4} and "glass.blur" in res["errors"]
        values = c.call("settings.get")["values"]
        assert values["glass.intensity"] == 0.4 and values["glass.blur"] == 1.0 and values["glass.shine"] == 1.0

        c.call("settings.patch", {"values": {"appearance.theme": "dark", "appearance.accent": "#E5484D"}})
        th = c.call("theme.get")
        assert th["theme"]["mode"] == "dark" and th["material"]["intensity"] == 0.4
        published = json.loads((data / "theme.json").read_text())
        assert published["mode"] == "dark"                      # what LaunchDeck reads

        # Click-through: the tall, top-most Glass windows only take input where their shapes are.
        import ctypes
        from ctypes import wintypes
        u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        u32.FindWindowW.restype = wintypes.HWND
        g32.CreateRectRgn.restype = wintypes.HANDLE
        u32.GetWindowRgnBox.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        hwnds = c.call("status.get")["hwnds"]          # this Shell's own windows (a real Glass may be running too)
        for kind, max_height in (("top", 80), ("dock", 55)):     # logical px; x2 allows any DPI up to 200%
            title = kind
            hwnd = next(h for k, h in hwnds.items() if k.endswith(":" + kind))
            assert u32.IsWindow(hwnd), f"{title} window not found"
            box = wintypes.RECT()
            kind = u32.GetWindowRgnBox(hwnd, ctypes.byref(box))
            assert kind in (2, 3), f"{title} has no input region (would block clicks)"   # SIMPLEREGION / COMPLEXREGION
            assert 0 < box.bottom - box.top <= max_height * 2, (title, box.top, box.bottom)

        assert isinstance(c.call("dock.apps")["apps"], list)
        cat = c.call("catalog.search", {"text": ""})
        assert isinstance(cat, list) and len(cat) > 5           # the real Applications folder

        # the engine the Shell supervises is up (its owner token exists and its pipe answers)
        deadline = time.time() + 20
        while time.time() < deadline and not c.call("status.get")["garvis"].get("engine"):
            time.sleep(0.5)
        assert c.call("status.get")["garvis"]["engine"] is True

        # The master power switch: OFF closes every surface and releases everything; ON brings it all back.
        before = c.call("status.get")
        assert before["powered"] is True and any(w.endswith(":dock") for w in before["windows"])
        assert before["island"] in before["screens"]
        c.call("shell.command", {"command": "power_off"})
        off = c.call("status.get")
        assert off["powered"] is False and off["windows"] == [] and off["appbars"] == 0 and off["taskbar_hidden"] is False
        assert not any(u32.IsWindow(h) for h in before["hwnds"].values())     # the windows are really gone
        assert c.call("settings.get")["values"]["system.enabled"] is False         # remembered across restarts
        assert c.call("settings.get")["values"]["glass.intensity"] == 0.4           # other settings untouched
        state = json.loads((data / "recovery-state.json").read_text())
        assert state["powered"] is False
        c.call("shell.command", {"command": "power_on"})
        on = c.call("status.get")
        assert on["powered"] is True and on["windows"] == before["windows"]
        assert all(u32.IsWindow(h) for h in on["hwnds"].values()) and len(on["hwnds"]) == len(before["hwnds"])

        mk = c.call("markets.get")
        assert set(mk) >= {"enabled", "indices", "watchlist", "status", "label"}

        c.call("shell.command", {"command": "quit"})
    finally:
        c.__exit__(None, None, None)
    assert proc.wait(30) == 0
    state = json.loads((data / "recovery-state.json").read_text())
    assert state["clean_exit"] is True
    err = proc.errlog.read_text(encoding="utf-8", errors="replace")
    assert "Traceback" not in err, err[-3000:]
    assert "TypeError" not in err, err[-3000:]       # no QML binding errors, including during shutdown


def test_second_instance_exits_immediately(shell, tmp_path):
    proc, data = shell
    c = connect()
    c.__exit__(None, None, None)
    env = dict(os.environ)
    second = subprocess.run([sys.executable, "-m", "glass.shell", "--test-mode", "--no-watchdog"], cwd=str(ROOT),
                            env={k: v for k, v in env.items() if not k.startswith("QT_")}, timeout=60, capture_output=True)
    assert second.returncode == 0
    assert proc.poll() is None    # the first one is unaffected


def test_switched_off_glass_starts_off_and_switches_on(tmp_path, monkeypatch):
    """After a reboot, or a watchdog restart, while Glass was switched off: the Shell stays resident with nothing on
    screen and the taskbar untouched, until it is switched on."""
    data = tmp_path / "glass"
    suffix = "t" + uuid.uuid4().hex[:8]
    monkeypatch.setenv("GLASS_DATA_DIR", str(data))
    monkeypatch.setenv("GLASS_PIPE_SUFFIX", suffix)
    from glass.core import paths
    from glass.core.settings import SettingsStore
    SettingsStore(paths.settings_db()).patch({"system.enabled": False})
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
    env.update(GLASS_DATA_DIR=str(data), GLASS_PIPE_SUFFIX=suffix, LAUNCHDECK_DATA_DIR=str(tmp_path / "ld"))
    errlog = open(tmp_path / "err.txt", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "glass.shell", "--test-mode", "--no-watchdog", "--no-engine"], cwd=str(ROOT),
                            env=env, stdout=subprocess.DEVNULL, stderr=errlog)
    try:
        c = connect()
        try:
            st = c.call("status.get")
            assert st["powered"] is False and st["windows"] == [] and st["appbars"] == 0 and st["taskbar_hidden"] is False
            c.call("shell.command", {"command": "power_on"})
            st = c.call("status.get")
            assert st["powered"] is True and st["windows"]
            c.call("shell.command", {"command": "quit"})
        finally:
            c.__exit__(None, None, None)
        assert proc.wait(30) == 0
    finally:
        errlog.close()
        if proc.poll() is None:
            proc.kill()
    err = (tmp_path / "err.txt").read_text(encoding="utf-8", errors="replace")
    assert "Traceback" not in err, err[-3000:]
