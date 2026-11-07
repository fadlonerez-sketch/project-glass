"""GlassController (notification rules, activity, hover vs click) and the Shell API server over a real pipe."""
import threading
import time

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from glass.core import security
from glass.core.pipeclient import PipeClient
from glass.core.settings import SettingsStore
from glass.shell.controller import GlassController
from glass.shell.server import ShellServer


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


def pump(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def glass(qapp, tmp_path):
    store = SettingsStore(tmp_path / "s.db")
    return GlassController(store), store


def test_notifications_follow_rules(glass):
    g, store = glass
    g.notify({"app": "Mail", "title": "Hi"})
    pump()
    assert g.state == "notification" and g.statePayload["title"] == "Hi"
    g.dismissNotification()
    store.patch({"notifications.dnd": True})
    pump()
    g.notify({"app": "Mail", "title": "quiet"})
    assert g.state != "notification"
    g.notify({"app": "Mail", "title": "urgent"}, priority="high")
    assert g.state == "notification" and g.statePayload["title"] == "urgent"
    assert [n["title"] for n in g.notifications][:3] == ["urgent", "quiet", "Hi"]   # history keeps everything


def test_app_rules_and_silent(glass):
    g, store = glass
    store.patch({"notifications.apps": {"Spam": {"enabled": False}, "Quiet": {"show": "silent"}}})
    pump()
    g.notify({"app": "Spam", "title": "x"})
    assert all(n.get("app") != "Spam" for n in g.notifications)
    g.notify({"app": "Quiet", "title": "y"})
    assert g.state != "notification" and g.notifications[0]["title"] == "y"


def test_volume_change_pulses_activity(glass):
    g, _ = glass
    g._on_audio({"available": True, "volume": 0.4, "muted": False, "device": "x"})   # initial: no pulse
    assert g.state == "idle"
    g._on_audio({"available": True, "volume": 0.5, "muted": False, "device": "x"})
    assert g.state == "activity" and g.statePayload["kind"] == "volume"


class FakeCursor:
    """Stands in for the real pointer position: tests never read or move the user's mouse."""
    def __init__(self):
        self.pos = (500, 10)

    def __call__(self):
        return self.pos


def test_hover_and_click_are_distinct(glass):
    g, store = glass
    cursor = g._cursor = FakeCursor()
    store.patch({"topbar.media.expand_delay_ms": 0})
    pump()
    g._on_media({"present": True, "playing": True, "title": "Song"})
    assert g.state == "media"
    g.pillClick()
    assert g.state == "control_center"
    g.pillClick()
    cursor.pos = (520, 12)                 # the user moves onto the pill
    g.pillEnter()
    pump(30)
    assert g.state == "media_expanded"
    g.closeAll()
    assert g.state == "media"


def test_garvis_activity_state_and_indicator_setting(glass):
    g, store = glass
    g.set_garvis(engine=True, active=True, app="Notepad")
    assert g.state == "garvis"
    g.set_garvis(stopped=True)
    assert g.state == "idle"
    g.set_garvis(stopped=False)
    store.patch({"garvis.indicator": False})
    pump()
    g.set_garvis(active=True)
    assert g.state == "idle"


def test_theme_tokens_follow_settings_and_publish_theme_json(glass, isolated_data):
    g, store = glass
    store.patch({"appearance.theme": "dark", "appearance.accent": "#2F7CF6"})
    pump()
    assert g.theme["mode"] == "dark" and g.theme["accent"]
    assert (isolated_data / "theme.json").exists()
    store.patch({"glass.intensity": 0.6})
    pump()
    assert g.material["intensity"] == 0.6 and g.material["blur"] == 1.0


# ------------------------------------------------------------------ Shell API over a real pipe

@pytest.fixture
def server(qapp):
    token = security.new_token()
    calls = []
    srv = ShellServer({"echo": lambda p: {"echo": p}, "boom": lambda p: 1 / 0},
                      {"slow": lambda p: (time.sleep(0.1), {"slow": True})[1]}, token_reader=lambda: token)
    assert srv.listen()
    yield srv, token
    srv.close()


def run_client(token, steps):
    out = {}

    def work():
        try:
            with PipeClient("Shell", token=token, timeout=3) as c:
                for name, method, params in steps:
                    try:
                        out[name] = c.call(method, params)
                    except Exception as exc:  # noqa: BLE001
                        out[name] = exc
        except Exception as exc:  # noqa: BLE001
            out["connect"] = exc
    t = threading.Thread(target=work)
    t.start()
    deadline = time.time() + 5
    while t.is_alive() and time.time() < deadline:
        pump(20)
    t.join(1)
    return out


def test_server_round_trip_and_errors(server):
    srv, token = server
    out = run_client(token, [("echo", "echo", {"a": 1}), ("async", "slow", {}), ("unknown", "nope", {}), ("boom", "boom", {})])
    assert out["echo"] == {"echo": {"a": 1}}
    assert out["async"] == {"slow": True}
    assert getattr(out["unknown"], "code", "") == "unknown_method"
    assert getattr(out["boom"], "code", "") == "internal"


def test_server_rejects_wrong_token(server):
    srv, token = server
    out = run_client("not-the-token", [("echo", "echo", {})])
    assert getattr(out.get("connect"), "code", "") == "unauthorized"


def test_music_starting_under_a_resting_pointer_does_not_open_the_player(glass):
    """The pill grows when music starts; if the pointer happens to rest there, that is not a hover."""
    g, store = glass
    cursor = g._cursor = FakeCursor()
    store.patch({"topbar.media.expand_delay_ms": 0})
    pump()
    g._on_media({"present": True, "playing": True, "title": "Song"})   # pill changes shape under the pointer
    g.pillEnter()                                                       # reported by the window system
    pump(200)
    assert g.state == "media" and g.pillArmPending
    cursor.pos = (503, 10)                                              # now the user actually moves
    g.pillMove()
    pump(30)
    assert g.state == "media_expanded"
    g.pillLeave()
    pump(600)
    assert g.state == "media"


def test_hover_responds_within_the_intent_delay(glass):
    g, store = glass
    cursor = g._cursor = FakeCursor()
    g._on_media({"present": True, "playing": True, "title": "Song"})
    pump(20)
    cursor.pos = (640, 14)
    start = time.monotonic()
    g.pillEnter()
    while g.state != "media_expanded" and time.monotonic() - start < 1.0:
        pump(5)
    took = time.monotonic() - start
    assert g.state == "media_expanded"
    assert took < store.get("topbar.media.expand_delay_ms") / 1000 + 0.06, took


def test_island_screen_and_power_state(glass):
    g, _ = glass
    seen = []
    g.islandChanged.connect(lambda: seen.append(g.islandScreen))
    g.set_island_screen("DISPLAY2")
    g.set_island_screen("DISPLAY2")
    assert seen == ["DISPLAY2"]
    states = []
    g.poweredChanged.connect(lambda: states.append((g.powered, g.powerBusy)))
    g.set_powered(True, busy=True)
    g.set_powered(False)
    assert states == [(True, True), (False, False)] and g.powered is False


# ------------------------------------------------------------------ Shell API: local-only, fail closed

def _raw_connect(name):
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    assert sock.waitForConnected(2000)
    return sock


def _settle(srv, sock, refused, timeout=2.0):
    from PySide6.QtNetwork import QLocalSocket
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump(20)
        if refused and sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            return
        if not refused and srv._clients:
            return


def test_server_refuses_remote_client(server, monkeypatch):
    from PySide6.QtNetwork import QLocalSocket
    srv, _ = server
    monkeypatch.setattr(security, "pipe_client_info",
                        lambda h: {"pid": 1, "image": "x", "remote": True, "computer": "EVIL"})
    sock = _raw_connect(srv.name)
    _settle(srv, sock, refused=True)
    assert sock.state() == QLocalSocket.LocalSocketState.UnconnectedState
    assert srv._clients == []


def test_server_refuses_client_it_cannot_identify(server, monkeypatch):
    from PySide6.QtNetwork import QLocalSocket
    srv, _ = server

    def boom(h):
        raise OSError("lookup failed")
    monkeypatch.setattr(security, "pipe_client_info", boom)
    sock = _raw_connect(srv.name)
    _settle(srv, sock, refused=True)
    assert sock.state() == QLocalSocket.LocalSocketState.UnconnectedState
    assert srv._clients == []


@pytest.mark.parametrize("bad", [None, {}, {"pid": 1, "remote": "no"}])
def test_server_refuses_malformed_client_info(server, monkeypatch, bad):
    from PySide6.QtNetwork import QLocalSocket
    srv, _ = server
    monkeypatch.setattr(security, "pipe_client_info", lambda h: bad)
    sock = _raw_connect(srv.name)
    _settle(srv, sock, refused=True)
    assert sock.state() == QLocalSocket.LocalSocketState.UnconnectedState
    assert srv._clients == []


def test_server_accepts_local_client(server):
    srv, _ = server            # the real lookup: this test process is a local client
    sock = _raw_connect(srv.name)
    _settle(srv, sock, refused=False)
    assert len(srv._clients) == 1
