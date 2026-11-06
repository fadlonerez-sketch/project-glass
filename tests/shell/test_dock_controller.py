"""DockModel diffing and DockController's window -> application mapping (fake tracker, real registry)."""
import random
import time

import pytest
from PySide6.QtCore import QObject, Signal

from glass.core.apps import AppRegistry
from glass.core.settings import SettingsStore
from glass.shell.dock import DockController, DockModel
from glass.win.appwin import AppCatalog, CatalogEntry, WindowInfo
from glass.win.tracker import Snapshot, TrackedWindow


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


# ------------------------------------------------------------------ model diffing

def _rows(uids):
    return [{"uid": u, "kind": "app", "name": u} for u in uids]


@pytest.mark.parametrize("seed", range(25))
def test_model_apply_reaches_any_target_order(qapp, seed):
    rnd = random.Random(seed)
    m = DockModel()
    events = []
    m.rowsInserted.connect(lambda *a: events.append("ins"))
    m.rowsRemoved.connect(lambda *a: events.append("rem"))
    m.rowsMoved.connect(lambda *a: events.append("mov"))
    pool = [f"u{i}" for i in range(12)]
    for _ in range(6):
        target = rnd.sample(pool, rnd.randint(0, 10))
        m.apply(_rows(target))
        assert [r["uid"] for r in m.items()] == target
        assert m.rowCount() == len(target)


def test_model_updates_in_place(qapp):
    m = DockModel()
    m.apply([{"uid": "a", "kind": "app", "name": "A", "focused": False}])
    changed = []
    m.dataChanged.connect(lambda tl, br, roles: changed.append(list(roles)))
    m.apply([{"uid": "a", "kind": "app", "name": "A", "focused": True}])
    assert changed and m.items()[0]["focused"] is True


# ------------------------------------------------------------------ controller

class FakeTracker(QObject):
    changed = Signal(object)

    def __init__(self, garvis=()):
        super().__init__()
        self._g = set(garvis)

    def garvis_desktops(self):
        return set(self._g)


def win(hwnd, exe, aumid="", title="w", cls="Win", pid=100):
    return WindowInfo(hwnd=hwnd, title=title, cls=cls, pid=pid, exe=exe, aumid=aumid, rect=(0, 0, 800, 600),
                      minimized=False, cloak=0)


def tracked(info, current=True, desk="{D1}", started=1000.0):
    return TrackedWindow(info=info, on_current_desktop=current, desktop_id=desk, started=started)


@pytest.fixture
def setup(qapp, tmp_path):
    settings = SettingsStore(tmp_path / "s.db")
    reg = AppRegistry(tmp_path / "apps.db")
    cat = AppCatalog()
    cat.entries = [CatalogEntry("Google Chrome", "Chrome", r"C:\Chrome\chrome.exe"),
                   CatalogEntry("Notepad", "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App", "")]
    cat._by_key = {k: e for e in cat.entries for k in e.keys()}
    tracker = FakeTracker(garvis={"{GARVIS}"})
    dock = DockController(settings, reg, cat, tracker)
    return settings, reg, dock, tracker


def ids(dock, section=None):
    return [r["appId"] for r in dock.model.items() if r["kind"] == "app" and (section is None or r["section"] == section)]


def test_windows_become_apps_with_catalog_names(setup):
    settings, reg, dock, tracker = setup
    chrome = win(1, r"C:\Chrome\chrome.exe", aumid="Chrome")
    tracker.changed.emit(Snapshot((tracked(chrome),), foreground=1, taken=time.time()))
    rows = [r for r in dock.model.items() if r["kind"] == "app"]
    assert rows[0]["name"] == "Google Chrome" and rows[0]["focused"] and rows[0]["section"] == "open"
    assert dock.foregroundName == "Google Chrome"


def test_multiple_windows_one_entry_and_close_moves_to_recent(setup):
    settings, reg, dock, tracker = setup
    a, b = win(1, r"C:\Chrome\chrome.exe", aumid="Chrome"), win(2, r"C:\Chrome\chrome.exe", aumid="Chrome")
    tracker.changed.emit(Snapshot((tracked(a), tracked(b)), 0, time.time()))
    rows = [r for r in dock.model.items() if r["kind"] == "app"]
    assert len(rows) == 1 and rows[0]["windowCount"] == 2
    tracker.changed.emit(Snapshot((), 0, time.time()))
    assert ids(dock, "open") == [] and ids(dock, "recent") == ["aumid:chrome"]
    assert reg.get("aumid:chrome").last_closed is not None


def test_garvis_desktop_and_other_desktops(setup):
    settings, reg, dock, tracker = setup
    on_garvis = win(5, r"C:\Tools\research.exe", pid=7)
    elsewhere = win(6, r"C:\Apps\mail.exe", pid=8)
    tracker.changed.emit(Snapshot((tracked(on_garvis, current=False, desk="{GARVIS}"),
                                   tracked(elsewhere, current=False, desk="{D2}")), 0, time.time()))
    assert ids(dock) == []                      # neither shown; mail is running so it isn't "recent" either
    settings.patch({"dock.all_desktops": True})
    dock.refresh()
    assert ids(dock, "open") == [r"exe:c:\apps\mail.exe"]   # all desktops: mail shows, Garvis's desktop never


def test_pinned_app_on_another_desktop_stays_available(setup):
    settings, reg, dock, tracker = setup
    w = win(9, r"C:\Apps\mail.exe")
    tracker.changed.emit(Snapshot((tracked(w),), 0, time.time()))
    dock.pin(r"exe:c:\apps\mail.exe")
    tracker.changed.emit(Snapshot((tracked(w, current=False, desk="{D2}"),), 0, time.time()))
    row = next(r for r in dock.model.items() if r["kind"] == "app")
    assert row["otherDesktop"] is True and row["section"] == "open"


def test_launch_time_uses_process_start(setup):
    settings, reg, dock, tracker = setup
    tracker.changed.emit(Snapshot((tracked(win(1, r"C:\Apps\x.exe"), started=5000.0),), 0, time.time()))
    assert reg.get(r"exe:c:\apps\x.exe").last_launched == 5000.0


def test_generic_hosts_are_split_by_window_class(setup):
    settings, reg, dock, tracker = setup
    a = win(1, r"C:\Python\pythonw.exe", cls="Qt_GarvisWindow")
    b = win(2, r"C:\Python\pythonw.exe", cls="TkTopLevel")
    tracker.changed.emit(Snapshot((tracked(a), tracked(b)), 0, time.time()))
    assert len(ids(dock, "open")) == 2


def test_layout_has_launcher_separators_and_widgets(setup):
    settings, reg, dock, tracker = setup
    reg.ensure(__import__("glass.core.apps", fromlist=["AppRecord"]).AppRecord(app_id="r", name="R"))
    reg.record_launch("r", 10)
    tracker.changed.emit(Snapshot((tracked(win(1, r"C:\Apps\x.exe")),), 0, time.time()))
    kinds = [r["kind"] for r in dock.model.items()]
    assert kinds[0] == "launcher" and kinds.count("separator") == 2 and kinds[-1] == "widget"
    assert dock.kinds == [[r["kind"], r["widgetType"]] for r in dock.model.items()]
