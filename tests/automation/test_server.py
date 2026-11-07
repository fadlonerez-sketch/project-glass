"""In-process tests of the pipe server's session logic with a fake engine (no UI Automation):
remote-client rejection, hello/auth, ordering, admin gating, stop broadcast, framing errors."""
from __future__ import annotations

import os
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket

from glass.automation import server as server_mod
from glass.automation.inputs import FakeInput
from glass.automation.server import AutomationServer
from glass.automation.store import Store
from glass.core import ipc, security


class _Events:
    def drop_session(self, sid):
        pass


class FakeEngine:
    def __init__(self, store, input_backend, activity, sink):
        self.store, self.activity = store, activity
        self.events = _Events()
        self.calls = []

    def handle(self, ctx, method, params):
        self.calls.append((ctx.client, method))
        if method == "slow":
            time.sleep(0.2)
        if method == "boom":
            raise ipc.ProtocolError(ipc.ErrorCode.NOT_FOUND, "nope")
        if method == "act":
            self.activity(client=ctx.client, method="element.act", target="App — Win", outcome="ok",
                          detail="invoke", app="App", title="Win")
        return {"method": method, "n": params.get("n")}

    def admin(self, method, p):
        return {"admin": method}


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump(app, cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@pytest.fixture
def srv(app, tmp_path, monkeypatch):
    monkeypatch.setenv("GLASS_DATA_DIR", str(tmp_path))
    store = Store(tmp_path / "a.db")
    store.ensure_client_tokens()
    name = f"ProjectGlass.Automation.unit-{os.getpid()}-{time.monotonic_ns()}"
    s = AutomationServer(FakeEngine, store, name, FakeInput())
    assert s.listen()
    yield s
    s.close()
    store.close()


class Conn:
    def __init__(self, app, name):
        self.app = app
        self.sock = QLocalSocket()
        self.dec = ipc.FrameDecoder()
        self.msgs = []
        self.sock.readyRead.connect(lambda: self.msgs.extend(self.dec.feed(bytes(self.sock.readAll().data()))))
        self.sock.connectToServer(name)
        assert self.sock.waitForConnected(2000)
        self.ids = 0

    def send(self, method, params=None):
        self.ids += 1
        self.sock.write(ipc.encode(ipc.request(self.ids, method, params)))
        self.sock.flush()
        return self.ids

    def reply(self, mid, timeout=3.0):
        pump(self.app, lambda: any(m.get("id") == mid for m in self.msgs), timeout)
        return next(m for m in self.msgs if m.get("id") == mid)

    def call(self, method, params=None):
        return self.reply(self.send(method, params))


def hello(c, token):
    return c.call("hello", {"protocol": 1, "client": "x", "token": token})


def test_remote_clients_are_rejected(app, srv, monkeypatch):
    monkeypatch.setattr(server_mod.security, "pipe_client_info",
                        lambda h: {"pid": 1, "image": "x", "remote": True, "computer": "EVIL"})
    c = Conn(app, srv.name)
    assert pump(app, lambda: c.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert srv.sessions == {}


def test_unidentifiable_clients_are_rejected(app, srv, monkeypatch):
    def boom(h):
        raise OSError("lookup failed")
    monkeypatch.setattr(server_mod.security, "pipe_client_info", boom)
    c = Conn(app, srv.name)
    assert pump(app, lambda: c.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert srv.sessions == {}


@pytest.mark.parametrize("bad", [None, {}, {"pid": 1, "remote": "no"}])
def test_malformed_client_info_is_rejected(app, srv, monkeypatch, bad):
    monkeypatch.setattr(server_mod.security, "pipe_client_info", lambda h: bad)
    c = Conn(app, srv.name)
    assert pump(app, lambda: c.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    assert srv.sessions == {}


def test_local_client_info_is_recorded(app, srv):
    c = Conn(app, srv.name)
    assert pump(app, lambda: len(srv.sessions) == 1)
    info = next(iter(srv.sessions.values())).info
    assert info["pid"] == os.getpid() and info["remote"] is False and info["image"].lower().endswith(".exe")


def test_hello_auth_and_version(app, srv):
    c = Conn(app, srv.name)
    r = c.call("windows.list")
    assert r["error"]["code"] == "unauthorized"
    r = c.call("hello", {"protocol": 99, "token": security.read_secret("garvis")})
    assert r["error"]["code"] == "unsupported_version" and r["error"]["data"]["supported"] == [1]
    r = hello(c, "wrong-token")
    assert r["error"]["code"] == "unauthorized"
    assert pump(app, lambda: c.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    c2 = Conn(app, srv.name)
    r = hello(c2, security.read_secret("garvis"))
    assert r["result"]["client"] == "garvis" and "act" in r["result"]["scopes"]
    assert r["result"]["protocol"] == 1 and "verify" in r["result"]["capabilities"]


def test_requests_answer_in_order_and_errors_propagate(app, srv):
    c = Conn(app, srv.name)
    hello(c, security.read_secret("garvis"))
    a = c.send("slow", {"n": 1})
    b = c.send("fast", {"n": 2})
    e = c.send("boom")
    c.reply(e)
    ids = [m["id"] for m in c.msgs if m.get("id") in (a, b, e)]
    assert ids == [a, b, e]
    assert c.reply(e)["error"]["code"] == "not_found"


def test_admin_requires_owner_and_stop_broadcasts(app, srv):
    g = Conn(app, srv.name)
    hello(g, security.read_secret("garvis"))
    assert g.call("admin.stop")["error"]["code"] == "forbidden_scope"
    o = Conn(app, srv.name)
    hello(o, security.read_secret("owner"))
    assert o.call("admin.subscribe")["result"]["subscribed"] is True
    assert o.call("admin.stop")["result"] == {"stopped": True}
    assert pump(app, lambda: any(m.get("method") == "stopped" for m in o.msgs))
    assert srv.store.stopped()
    assert o.call("admin.resume")["result"] == {"stopped": False}
    assert o.call("admin.permissions.get")["result"] == {"admin": "admin.permissions.get"}


def test_activity_and_control_state_reach_owner(app, srv):
    o = Conn(app, srv.name)
    hello(o, security.read_secret("owner"))
    o.call("admin.subscribe")
    g = Conn(app, srv.name)
    hello(g, security.read_secret("garvis"))
    g.call("act")
    assert pump(app, lambda: any(m.get("method") == "activity" for m in o.msgs))
    assert pump(app, lambda: any(m.get("method") == "control_state" and m["params"]["active"] for m in o.msgs))
    act = next(m for m in o.msgs if m.get("method") == "activity")["params"]
    assert act["client"] == "garvis" and act["app"] == "App" and act["outcome"] == "ok"


def test_malformed_frame_gets_error_and_disconnect(app, srv):
    c = Conn(app, srv.name)
    c.sock.write(b"\x03\x00\x00\x00{x}")
    c.sock.flush()
    assert pump(app, lambda: any("error" in m for m in c.msgs))
    assert pump(app, lambda: c.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState)
