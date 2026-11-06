"""Backdrop layout, glyph rendering, taskbar/recovery logic (Windows calls faked: nothing on the real
desktop changes), and the Shell + Control Center QML rendering offscreen without warnings."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from glass.shell.backdrop import layout_rect
from glass.win import shellbar

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.mark.parametrize("mode,expect", [
    # 1280x720 picture on a 2560x1600 monitor
    ("fill", (-142, 0, 2844, 1600)), ("fit", (0, 80, 2560, 1440)), ("stretch", (0, 0, 2560, 1600)),
    ("center", (640, 440, 1280, 720))])
def test_wallpaper_layout(mode, expect):
    r = layout_rect(1280, 720, 2560, 1600, mode)
    assert tuple(round(v) for v in (r.x(), r.y(), r.width(), r.height())) == pytest.approx(expect, abs=1)


def test_render_monitor_background_and_size(qapp, tmp_path):
    from glass.shell.backdrop import render_monitor
    img = render_monitor("", "fill", "#123456", (64, 32))
    assert (img.width(), img.height()) == (64, 32) and img.pixelColor(5, 5).name() == "#123456"


def test_every_glyph_renders(qapp):
    from glass.ui.glyphs import GLYPHS, render
    assert len(GLYPHS) >= 50
    for name in GLYPHS:
        img = render(f"icon/{name}/%23000000/1.7", 32)
        assert not img.isNull()
        assert any(img.pixelColor(x, y).alpha() > 0 for x in range(32) for y in range(32)), name
    for spec in ("wifi/0/none/%23000000", "wifi/3/wifi/%23ffffff", "speaker/0/1/%23000000",
                 "weather/clear/0/1", "weather/snow/1/0", "weather/thunder/1/1"):
        assert not render(spec, 40).isNull()


# ------------------------------------------------------------------ taskbar + recovery with faked Windows calls

@pytest.fixture
def fake_taskbar(monkeypatch):
    st = {"state": shellbar.ABS_ALWAYSONTOP, "visible": {101: True, 102: True}}
    monkeypatch.setattr(shellbar, "taskbar_windows", lambda: [101, 102])
    monkeypatch.setattr(shellbar, "get_taskbar_state", lambda: st["state"])
    monkeypatch.setattr(shellbar, "set_taskbar_state", lambda v: st.__setitem__("state", v))

    class U:
        def ShowWindow(self, h, cmd):
            st["visible"][h] = cmd != shellbar.SW_HIDE
        def IsWindowVisible(self, h):
            return st["visible"].get(h, True)
        def FindWindowW(self, *a):
            return 101
        def SetWinEventHook(self, *a):
            return 0
        def UnhookWinEvent(self, *a):
            return 1
        def SetForegroundWindow(self, h):
            return 1
    monkeypatch.setattr(shellbar, "user32", U())
    monkeypatch.setattr(shellbar, "window_pid", lambda h: 0)
    return st


def test_taskbar_hide_records_state_first_and_restores(fake_taskbar, tmp_path):
    state = tmp_path / "recovery-state.json"
    tb = shellbar.TaskbarController(state)
    tb.hide()
    saved = json.loads(state.read_text())
    assert saved["taskbar_hidden"] and saved["taskbar_original_state"] == shellbar.ABS_ALWAYSONTOP
    assert fake_taskbar["state"] & shellbar.ABS_AUTOHIDE and not any(fake_taskbar["visible"].values())
    tb.hide()   # hiding twice never overwrites the user's original setting
    assert json.loads(state.read_text())["taskbar_original_state"] == shellbar.ABS_ALWAYSONTOP
    tb.restore()
    assert fake_taskbar["state"] == shellbar.ABS_ALWAYSONTOP and all(fake_taskbar["visible"].values())
    assert json.loads(state.read_text())["taskbar_hidden"] is False


def test_watchdog_style_restore_from_state_file_alone(fake_taskbar, tmp_path):
    state = tmp_path / "recovery-state.json"
    shellbar.TaskbarController(state).hide()          # Glass "crashes" here: only the file remains
    assert shellbar.restore_taskbar_from_state(state) is True
    assert all(fake_taskbar["visible"].values()) and fake_taskbar["state"] == shellbar.ABS_ALWAYSONTOP
    assert shellbar.restore_taskbar_from_state(state) is False   # idempotent


def test_recovery_crash_budget(monkeypatch, isolated_data):
    from glass.recovery import __main__ as rec
    assert [len(rec._recent_crashes(1000.0 + i)) for i in range(4)] == [1, 2, 3, 4]
    assert len(rec._recent_crashes(5000.0)) == 1    # old crashes age out after 10 minutes


def test_recovery_restore_without_shell(fake_taskbar, monkeypatch, isolated_data):
    from glass.recovery import __main__ as rec
    from glass.core import paths
    monkeypatch.setattr(rec, "notify_work_area_changed", lambda: None)
    shellbar.TaskbarController(paths.state_file()).hide()
    result = rec.restore(stop_shell=True)
    assert result["taskbar_restored"] is True
    assert json.loads(paths.state_file().read_text())["clean_exit"] is True


def test_hotkey_parsing():
    assert shellbar.parse_hotkey("Ctrl+Alt+Shift+R") == (0x2 | 0x1 | 0x4, ord("R"))
    assert shellbar.parse_hotkey("ctrl+alt+shift+q")[1] == ord("Q")
    with pytest.raises(ValueError):
        shellbar.parse_hotkey("Hyper+R")


# ------------------------------------------------------------------ QML renders offscreen with zero warnings

def _child_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
    env["GLASS_DATA_DIR"] = str(tmp_path / "data")
    return env


@pytest.mark.slow
def test_shell_qml_renders_all_states_without_warnings(tmp_path):
    out = tmp_path / "preview"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "preview" / "render.py"), "--out", str(out),
                        "--modes", "light", "dark", "--intensity", "0", "1"],
                       capture_output=True, text=True, timeout=600, env=_child_env(tmp_path), cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-2000:]
    report = json.loads((out / "render-report.json").read_text())
    assert report["warnings"] == []
    assert len(report["files"]) == 72          # (8 top bar + 6 flyouts + 4 Dock) x 2 themes x 2 intensities


@pytest.mark.slow
def test_control_center_qml_renders_every_page_without_warnings(tmp_path):
    out = tmp_path / "cc"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "preview" / "render_cc.py"), "--out", str(out)],
                       capture_output=True, text=True, timeout=400, env=_child_env(tmp_path), cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-2000:]
    summary = json.loads(r.stdout[r.stdout.index("{"):])
    assert summary["warnings"] == [] and summary["count"] == 20      # 10 pages x 2 themes
