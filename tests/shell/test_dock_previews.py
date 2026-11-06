"""Window previews (DWM thumbnail host with a fake DWM), the Dock model's departure animation, drag-and-drop
reordering, island placement across displays, and the markets service -- all without touching the desktop."""
import time

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal

from glass.core import markets as mk
from glass.core.apps import AppRecord, AppRegistry
from glass.core.settings import SettingsStore
from glass.core.states import pick_island_screen
from glass.shell.dock import DockModel
from glass.win.thumbnails import ThumbnailHost, fit, to_device


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


def pump(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# ---------------------------------------------------------------------------------------------- thumbnails

class FakeDwm:
    """Records what would be asked of DWM. Windows: hwnd -> dict(alive, minimized, cloaked, size)."""

    def __init__(self, windows):
        self.windows = windows
        self.next = 100
        self.live: dict[int, dict] = {}      # thumb handle -> props
        self.registered: list[tuple[int, int]] = []

    def register(self, dest, src):
        if not self.windows.get(src, {}).get("alive", False) or self.windows[src].get("refuse"):
            return 0
        self.next += 1
        self.live[self.next] = {"src": src, "rect": None, "opacity": 0, "visible": False}
        self.registered.append((dest, src))
        return self.next

    def unregister(self, h):
        self.live.pop(h, None)

    def update(self, h, rect, opacity, visible):
        if h not in self.live:
            return False
        self.live[h].update(rect=rect, opacity=opacity, visible=visible)
        return True

    def source_size(self, h):
        return self.windows[self.live[h]["src"]].get("size", (1600, 1000))

    def is_window(self, hwnd):
        return self.windows.get(hwnd, {}).get("alive", False)

    def frame_size(self, hwnd):
        return self.windows.get(hwnd, {}).get("size", (1600, 1000))

    def cloaked(self, hwnd):
        return self.windows.get(hwnd, {}).get("cloaked", False)

    def minimized(self, hwnd):
        return self.windows.get(hwnd, {}).get("minimized", False)


def box(hwnd, x=10, y=20, w=220, h=136):
    return {"hwnd": hwnd, "x": x, "y": y, "w": w, "h": h}


def test_live_thumbnails_and_fallback_reasons():
    dwm = FakeDwm({1: {"alive": True}, 2: {"alive": True, "minimized": True}, 3: {"alive": True, "cloaked": True},
                   4: {"alive": False}, 5: {"alive": True, "refuse": True}})
    host = ThumbnailHost(999, api=dwm)
    status = host.show([box(1), box(2), box(3), box(4), box(5)], dpr=1.0)
    assert status == {1: "", 2: "minimized", 3: "elsewhere", 4: "gone", 5: "unsupported"}
    assert list(host.thumbs) == [1] and dwm.registered == [(999, 1)]


def test_thumbnail_is_aspect_fitted_in_device_pixels():
    dwm = FakeDwm({1: {"alive": True, "size": (1000, 1000)}})
    host = ThumbnailHost(1, api=dwm)
    host.show([box(1, x=10, y=20, w=200, h=100)], dpr=1.5)
    rect = next(iter(dwm.live.values()))["rect"]
    # a square window in a 200x100 box: 100x100 centred -> x 60..160, y 20..120 (logical) -> x1.5
    assert rect == (90, 30, 240, 180)
    assert fit(1600, 900, 160, 90) == (0.0, 0.0, 160.0, 90.0)
    assert to_device((0.5, 0.5, 10, 10), 1.25) == (1, 1, 13, 13)


def test_thumbnails_follow_the_wanted_set_and_are_cleaned_up():
    dwm = FakeDwm({1: {"alive": True}, 2: {"alive": True}})
    host = ThumbnailHost(1, api=dwm)
    host.show([box(1), box(2, x=250)], dpr=1.0)
    assert len(dwm.live) == 2
    host.show([box(2, x=10)], dpr=1.0)           # switched to another app's single window
    assert len(dwm.live) == 1 and list(host.thumbs) == [2]
    dwm.windows[2]["alive"] = False              # the window closed while shown
    assert host.prune() == [2] and dwm.live == {}
    host.show([box(1)], dpr=1.0)
    host.clear()
    assert dwm.live == {} and host.thumbs == {}


def test_thumbnails_fade_in_and_hide_at_once():
    dwm = FakeDwm({1: {"alive": True}})
    host = ThumbnailHost(1, api=dwm)
    host.show([box(1)], dpr=1.0)
    t = next(iter(dwm.live.values()))
    assert t["opacity"] == 0
    steps = 0
    while host.fade_step():
        steps += 1
    assert t["opacity"] == 255 and t["visible"] and steps <= ThumbnailHost.FADE_STEPS
    host.hide_all()
    assert t["opacity"] == 0 and t["visible"] is False


# ---------------------------------------------------------------------------------------------- dock model

def row(uid, **kw):
    base = {"uid": uid, "kind": "app", "appId": uid, "name": uid, "section": "open", "pinned": False, "running": True,
            "focused": False, "windowCount": 1, "icon": "", "launching": False, "otherDesktop": False,
            "widgetType": "", "widgetId": "", "attention": False}
    base.update(kw)
    return base


def test_departing_icons_stay_in_place_flagged_leaving(qapp):
    m = DockModel()
    m.apply([row("a"), row("b"), row("c")])
    m.apply([row("a"), row("c")], keep_leaving={"b"})
    assert [(r["uid"], r["leaving"]) for r in m.items()] == [("a", False), ("b", True), ("c", False)]
    m.apply([row("a"), row("c")])                 # after the fade
    assert [r["uid"] for r in m.items()] == ["a", "c"]


def test_departing_icon_coming_back_is_not_leaving(qapp):
    m = DockModel()
    m.apply([row("a"), row("b")])
    m.apply([row("a")], keep_leaving={"b"})
    m.apply([row("a"), row("b")])
    assert [(r["uid"], r["leaving"]) for r in m.items()] == [("a", False), ("b", False)]


class FakeTracker(QObject):
    changed = Signal(object)
    foregroundChanged = Signal(int)

    def garvis_desktops(self):
        return set()


def make_dock(tmp_path):
    from glass.shell.dock import DockController
    from glass.win import appwin
    settings = SettingsStore(tmp_path / "s.db")
    registry = AppRegistry(tmp_path / "apps.db")
    catalog = appwin.AppCatalog()
    dock = DockController(settings, registry, catalog, FakeTracker())
    return dock, registry, settings


def test_drag_reorder_within_a_section_keeps_other_pins_in_place(qapp, tmp_path):
    dock, reg, _ = make_dock(tmp_path)
    for a in ("a", "b", "c", "d", "e"):
        reg.ensure(AppRecord(app_id=a, name=a))
        reg.pin(a)
    # suppose a, c, e are running (Open section) and b, d are closed (Recent section): reorder the Open section
    dock.reorderPinned(["e", "a", "c"])
    assert [r.app_id for r in reg.pinned()] == ["e", "b", "a", "d", "c"]
    dock.reorderPinned(["d", "b"])
    assert [r.app_id for r in reg.pinned()] == ["e", "d", "a", "b", "c"]
    dock.reorderPinned(["a", "a"])                # nonsense is ignored
    assert [r.app_id for r in reg.pinned()] == ["e", "d", "a", "b", "c"]


def test_layout_slot_is_stable_and_cached(qapp, tmp_path):
    dock, reg, _ = make_dock(tmp_path)
    dock._model.apply([row("launcher", kind="launcher", section=""), row("app:a"), row("app:b")])
    a = dock.layoutFor(1900.0, 38.0, 10.0, True)
    b = dock.layoutFor(1900.0, 38.0, 10.0, True)
    assert a == b and a["slots"]["app:a"]["len"] == 38


# ---------------------------------------------------------------------------------------------- displays

def test_island_follows_the_active_display():
    tops = ["DELL", "LAPTOP"]
    assert pick_island_screen(tops, "DELL", "active", "LAPTOP", "DELL") == "LAPTOP"
    assert pick_island_screen(tops, "DELL", "active", "", "LAPTOP") == "LAPTOP"      # desktop in front: stay
    assert pick_island_screen(tops, "DELL", "active", "TV", "LAPTOP") == "LAPTOP"     # a display without a top bar
    assert pick_island_screen(tops, "DELL", "primary", "LAPTOP", "LAPTOP") == "DELL"
    assert pick_island_screen(["DELL"], "DELL", "active", "LAPTOP", "") == "DELL"     # top bar only on the main display
    assert pick_island_screen(["LAPTOP"], "DELL", "active", "", "") == "LAPTOP"
    assert pick_island_screen([], "DELL", "active", "DELL", "") == ""


# ---------------------------------------------------------------------------------------------- markets service

class FakeClient:
    def __init__(self):
        self.answer = ({}, {})
        self.calls = 0
        self.cache = {}

    def quotes(self, symbols):
        self.calls += 1
        return self.answer

    def cached(self, symbols):
        return {s: q for s, q in self.cache.items() if s in symbols}

    def search(self, text):
        return []


def quote(symbol, price=100.0, prev=99.0, market_time=None, from_cache=False, fetched=None, session=None):
    now = time.time()
    start, end = session if session else (now - 3600, now + 3600)
    return mk.Quote(symbol=symbol, name=symbol, price=price, previous_close=prev, change=price - prev,
                    change_pct=(price - prev) / prev * 100, currency="USD", instrument="EQUITY", exchange="X",
                    market_time=market_time if market_time is not None else now - 30, session_start=start, session_end=end,
                    pre_start=start - 1800, post_end=end + 1800, day_high=price, day_low=price, spark=(1.0, 2.0),
                    fetched_at=fetched if fetched is not None else now, from_cache=from_cache)


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        pump(20)
    return cond()


def test_markets_cache_is_never_live_and_fresh_quotes_are(qapp, tmp_path):
    from glass.shell.markets import MarketsService
    settings = SettingsStore(tmp_path / "s.db")
    settings.patch({"markets.watchlist": ["AAPL"], "markets.show_indices": False})
    client = FakeClient()
    client.cache = {"AAPL": quote("AAPL", from_cache=True, fetched=time.time() - 7200)}
    client.answer = ({}, {"AAPL": "No internet connection"})
    svc = MarketsService(settings, client=client)
    svc.start()
    assert wait_for(lambda: client.calls == 1 and not svc._busy)
    e = svc.data["watchlist"][0]
    assert e["price"] == 100.0 and e["status"] == "stale" and e["live"] is False
    assert svc.data["status"] == "stale" and svc.data["label"].startswith("Not updated since")
    # the network comes back
    client.answer = ({"AAPL": quote("AAPL")}, {})
    svc.refresh()
    assert wait_for(lambda: client.calls == 2 and not svc._busy)
    e = svc.data["watchlist"][0]
    assert e["live"] is True and svc.data["status"] == "live" and svc.data["updated"].startswith("Updated")
    svc.stop()


def test_markets_delayed_quote_is_labelled_delayed(qapp, tmp_path):
    from glass.shell.markets import MarketsService
    settings = SettingsStore(tmp_path / "s.db")
    settings.patch({"markets.watchlist": ["MSFT"], "markets.show_indices": False})
    client = FakeClient()
    client.answer = ({"MSFT": quote("MSFT", market_time=time.time() - 47 * 60)}, {})
    svc = MarketsService(settings, client=client)
    svc.start()
    assert wait_for(lambda: client.calls == 1 and not svc._busy)
    assert svc.data["status"] == "delayed" and "47 min" in svc.data["label"]
    svc.stop()


def test_markets_off_fetches_nothing(qapp, tmp_path):
    from glass.shell.markets import MarketsService
    settings = SettingsStore(tmp_path / "s.db")
    settings.patch({"markets.enabled": False})
    client = FakeClient()
    svc = MarketsService(settings, client=client)
    svc.start()
    pump(200)
    assert client.calls == 0 and svc.data["status"] == "off"
    svc.stop()
