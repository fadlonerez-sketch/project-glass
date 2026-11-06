"""Qt client for the Automation pipe -- used by the Shell and the Control Center with the *owner* token.

    client = EngineClient(subscribe_admin=True)
    client.connectedChanged.connect(...)            # bool
    client.notification.connect(lambda method, params: ...)   # 'activity' | 'control_state' | 'stopped' | 'event'
    client.start()
    client.call("admin.permissions.get", {}, lambda result, error: ...)

`call` invokes the callback exactly once with (result, None) or (None, {"code", "message", ...}). When the
engine isn't connected the callback gets an `unavailable` error immediately. The client reconnects with
backoff (0.5 s -> 5 s) forever; after each (re)connect it sends hello and, if asked, admin.subscribe.
"""
from __future__ import annotations

import itertools
import logging

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QLocalSocket

from glass.core import ipc, security

log = logging.getLogger("glass.engineclient")


class EngineClient(QObject):
    connectedChanged = Signal(bool)
    notification = Signal(str, object)
    helloReceived = Signal(object)

    def __init__(self, token: str | None = None, client_name: str = "owner", subscribe_admin: bool = False,
                 pipe_name: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._token_override = token
        self.client_name = client_name
        self.subscribe_admin = subscribe_admin
        self.pipe_name = pipe_name or security.pipe_name("Automation")
        self.sock = QLocalSocket(self)
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.readyRead.connect(self._on_ready)
        self.sock.errorOccurred.connect(self._on_error)
        self._decoder = ipc.FrameDecoder()
        self._ids = itertools.count(1)
        self._callbacks: dict[int, object] = {}
        self._ready = False
        self._backoff = 0.5
        self._running = False
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._connect)
        self.hello: dict | None = None
        self.last_error = ""

    # ------------------------------------------------------------------ public API
    @property
    def connected(self) -> bool:
        return self._ready

    def start(self) -> None:
        self._running = True
        self._connect()

    def stop(self) -> None:
        self._running = False
        self._retry.stop()
        self.sock.abort()

    def call(self, method: str, params: dict | None = None, callback=None) -> None:
        if not self._ready:
            if callback:
                callback(None, {"code": "unavailable", "message": self.last_error or "Glass.Automation is not running"})
            return
        self._send(method, params, callback)

    # ------------------------------------------------------------------ internals
    def _token(self) -> str:
        return self._token_override or security.read_secret(self.client_name) or ""

    def _send(self, method, params, callback) -> None:
        mid = next(self._ids)
        if callback:
            self._callbacks[mid] = callback
        self.sock.write(ipc.encode(ipc.request(mid, method, params)))
        self.sock.flush()

    @Slot()
    def _connect(self) -> None:
        if not self._running or self.sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            return
        self._decoder = ipc.FrameDecoder()
        self.sock.connectToServer(self.pipe_name)

    @Slot()
    def _on_connected(self) -> None:
        self._backoff = 0.5

        def on_hello(result, error):
            if error:
                self.last_error = error.get("message", "hello failed")
                log.warning("engine hello failed: %s", self.last_error)
                self.sock.disconnectFromServer()
                return
            self.hello = result
            self._ready = True
            self.helloReceived.emit(result)
            self.connectedChanged.emit(True)
            if self.subscribe_admin:
                self._send("admin.subscribe", {}, lambda r, e: r and self.notification.emit("subscribed", r))

        self._send("hello", {"protocol": ipc.PROTOCOL_VERSION, "client": self.client_name,
                             "token": self._token()}, on_hello)

    @Slot()
    def _on_disconnected(self) -> None:
        was = self._ready
        self._ready = False
        pending, self._callbacks = self._callbacks, {}
        for cb in pending.values():
            cb(None, {"code": "unavailable", "message": "the engine connection closed"})
        if was:
            self.connectedChanged.emit(False)
        self._schedule_retry()

    @Slot(QLocalSocket.LocalSocketError)
    def _on_error(self, _err) -> None:
        self.last_error = self.sock.errorString()
        if self.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self._schedule_retry()

    def _schedule_retry(self) -> None:
        if self._running and not self._retry.isActive():
            self._retry.start(int(self._backoff * 1000))
            self._backoff = min(self._backoff * 2, 5.0)

    @Slot()
    def _on_ready(self) -> None:
        try:
            msgs = self._decoder.feed(bytes(self.sock.readAll().data()))
        except ipc.ProtocolError:
            self.sock.abort()
            return
        for m in msgs:
            mid = m.get("id")
            if mid is None and "method" in m:
                self.notification.emit(m["method"], m.get("params") or {})
                continue
            cb = self._callbacks.pop(mid, None)
            if cb:
                cb(m.get("result"), m.get("error"))
