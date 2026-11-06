"""EngineClient (the Qt client the Shell and Control Center use) against the real engine process."""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication

from glass.automation.qtclient import EngineClient
from tests.automation.conftest import PIPE


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump(app, cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def test_owner_client_connects_subscribes_and_calls(app, engine, tokens):
    c = EngineClient(token=tokens["owner"], subscribe_admin=True, pipe_name=PIPE)
    states, notes, results = [], [], []
    c.connectedChanged.connect(states.append)
    c.notification.connect(lambda m, p: notes.append((m, p)))
    c.call("engine.status", {}, lambda r, e: results.append(e))  # before connecting
    assert results and results[0]["code"] == "unavailable"
    c.start()
    assert pump(app, lambda: c.connected)
    assert states == [True] and c.hello["client"] == "owner"
    assert pump(app, lambda: any(m == "subscribed" for m, _ in notes))
    got = []
    c.call("admin.permissions.get", {}, lambda r, e: got.append((r, e)))
    assert pump(app, lambda: got)
    assert got[0][1] is None and "garvis" in got[0][0]["clients"]
    c.call("admin.stop", {}, lambda r, e: got.append((r, e)))
    assert pump(app, lambda: any(m == "stopped" and p["stopped"] for m, p in notes))
    c.call("admin.resume", {}, lambda r, e: got.append((r, e)))
    assert pump(app, lambda: any(m == "stopped" and not p["stopped"] for m, p in notes))
    c.stop()


def test_bad_token_keeps_retrying_without_connecting(app, engine):
    c = EngineClient(token="wrong", pipe_name=PIPE)
    c.start()
    pump(app, lambda: False, timeout=1.0)
    assert not c.connected and "token" in c.last_error.lower()
    c.stop()


def test_missing_engine_reports_unavailable(app):
    c = EngineClient(token="x", pipe_name="ProjectGlass.Automation.nobody")
    c.start()
    pump(app, lambda: False, timeout=0.5)
    out = []
    c.call("engine.status", {}, lambda r, e: out.append(e))
    assert out[0]["code"] == "unavailable" and not c.connected
    c.stop()
