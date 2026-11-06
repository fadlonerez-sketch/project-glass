"""The Automation pipe server: QLocalServer (current-user ACL), sessions, auth, dispatch, notifications.

Requests of one session are processed strictly in order; sessions run concurrently on a small pool of
MTA worker threads. Results and notifications are marshalled back to the Qt thread through a signal.
"""
from __future__ import annotations

import concurrent.futures
import itertools
import logging
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from glass import __version__
from glass.automation import uia as U
from glass.automation.engine import Ctx, Engine
from glass.core import ipc, security
from glass.core.ipc import ErrorCode, ProtocolError

log = logging.getLogger("glass.automation")
CAPABILITIES = ["windows", "tree", "find", "act", "text", "window_ops", "keys", "watch", "wait", "verify", "coverage"]
CONTROL_IDLE_MS = 4000
_session_ids = itertools.count(1)


class Session:
    def __init__(self, sock: QLocalSocket, info: dict):
        self.id = f"c{next(_session_ids)}"
        self.sock = sock
        self.info = info
        self.decoder = ipc.FrameDecoder()
        self.client: str | None = None
        self.scopes: list[str] = []
        self.queue: list[dict] = []
        self.busy = False
        self.admin_subscribed = False
        self.closed = False


class _Relay(QObject):
    done = Signal(object, object)          # session, message dict
    activity = Signal(object)              # activity dict
    event = Signal(object, object)         # subscription, event dict
    note = Signal(object)                  # notify.post payload


class AutomationServer(QObject):
    stoppedChanged = Signal(bool)

    def __init__(self, engine_factory, store, name: str, input_backend, parent=None):
        super().__init__(parent)
        self.store = store
        self.name = name
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="glass-uia",
                                                          initializer=U.mta_init)
        self.relay = _Relay()
        self.relay.done.connect(self._on_done)
        self.relay.activity.connect(self._on_activity)
        self.relay.event.connect(self._on_event)
        self.sessions: dict[str, Session] = {}
        self.engine: Engine = self.pool.submit(
            engine_factory, store, input_backend,
            lambda **kw: self.relay.activity.emit(kw),
            lambda sub, ev: self.relay.event.emit(sub, ev)).result()
        self.engine.client_count = lambda: sum(1 for s in self.sessions.values() if s.client)
        self.engine.notify_sink = lambda note: self.relay.note.emit(note)
        self.relay.note.connect(lambda note: self._broadcast_admin("notification", note))
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._on_connection)
        self._control_timer = QTimer(self)
        self._control_timer.setSingleShot(True)
        self._control_timer.timeout.connect(self._control_idle)
        self._control_active: dict | None = None

    def listen(self) -> bool:
        if not self.server.listen(self.name):
            log.error("cannot listen on %s: %s", self.name, self.server.errorString())
            return False
        log.info("listening on \\\\.\\pipe\\%s", self.name)
        return True

    def close(self) -> None:
        self.server.close()
        for s in list(self.sessions.values()):
            s.sock.abort()
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ connections
    @Slot()
    def _on_connection(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            try:
                info = security.pipe_client_info(int(sock.socketDescriptor()))
            except Exception as exc:  # pragma: no cover - defensive
                info = {"pid": 0, "image": "", "remote": False, "error": str(exc)}
            if info.get("remote"):
                log.warning("rejected remote pipe client from %s", info.get("computer"))
                sock.abort()
                sock.deleteLater()
                continue
            session = Session(sock, info)
            self.sessions[session.id] = session
            sock.readyRead.connect(lambda s=session: self._on_ready(s))
            sock.disconnected.connect(lambda s=session: self._on_disconnected(s))
            log.info("client connected session=%s pid=%s image=%s", session.id, info.get("pid"), info.get("image"))

    def _on_disconnected(self, s: Session) -> None:
        if s.closed:
            return
        s.closed = True
        self.sessions.pop(s.id, None)
        self.pool.submit(self.engine.events.drop_session, s.id)
        s.sock.deleteLater()
        log.info("client disconnected session=%s client=%s", s.id, s.client)

    def _send(self, s: Session, msg: dict) -> None:
        if s.closed or s.sock.state() != QLocalSocket.LocalSocketState.ConnectedState:
            return
        try:
            s.sock.write(ipc.encode(msg))
            s.sock.flush()
        except ValueError as exc:
            if "id" in msg:
                s.sock.write(ipc.encode(ipc.error(msg["id"], ProtocolError(ErrorCode.INTERNAL, str(exc)))))

    def _on_ready(self, s: Session) -> None:
        try:
            msgs = s.decoder.feed(bytes(s.sock.readAll().data()))
        except ProtocolError as exc:
            self._send(s, ipc.error(None, exc))
            s.sock.disconnectFromServer()
            return
        for m in msgs:
            s.queue.append(m)
        self._pump(s)

    # ------------------------------------------------------------------ dispatch
    def _pump(self, s: Session) -> None:
        while not s.busy and s.queue and not s.closed:
            msg = s.queue.pop(0)
            mid = msg.get("id")
            method = msg.get("method")
            params = msg.get("params") or {}
            if not isinstance(method, str):
                self._send(s, ipc.error(mid, ProtocolError(ErrorCode.INVALID_PARAMS, "missing method")))
                continue
            try:
                if method == "hello":
                    self._send(s, ipc.response(mid, self._hello(s, params)))
                    continue
                if not s.client:
                    raise ProtocolError(ErrorCode.UNAUTHORIZED, "Send hello with a valid token first.")
                if method.startswith("admin."):
                    self._send(s, ipc.response(mid, self._admin(s, method, params)))
                    continue
            except ProtocolError as exc:
                self._send(s, ipc.error(mid, exc))
                if exc.code == ErrorCode.UNAUTHORIZED and method == "hello":
                    QTimer.singleShot(50, s.sock.disconnectFromServer)
                continue
            s.busy = True
            ctx = Ctx(session=s.id, client=s.client, scopes=list(s.scopes), pid=int(s.info.get("pid") or 0))
            fut = self.pool.submit(self._run, ctx, mid, method, params)
            fut.add_done_callback(lambda f, s=s: self.relay.done.emit(s, f.result()))

    def _run(self, ctx: Ctx, mid, method: str, params: dict) -> dict:
        try:
            return ipc.response(mid, self.engine.handle(ctx, method, params))
        except ProtocolError as exc:
            return ipc.error(mid, exc)
        except Exception as exc:
            log.exception("internal error in %s", method)
            return ipc.error(mid, ProtocolError(ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}"))

    @Slot(object, object)
    def _on_done(self, s: Session, msg: dict) -> None:
        s.busy = False
        self._send(s, msg)
        self._pump(s)

    def _hello(self, s: Session, p: dict) -> dict:
        proto = p.get("protocol")
        if proto != ipc.PROTOCOL_VERSION:
            raise ProtocolError(ErrorCode.VERSION, f"protocol {proto} is not supported",
                                {"supported": [ipc.PROTOCOL_VERSION]})
        auth = self.store.authenticate(str(p.get("token") or ""))
        if not auth:
            log.warning("hello with an invalid token (pid=%s image=%s)", s.info.get("pid"), s.info.get("image"))
            self.store.audit(str(p.get("client") or "?"), "hello", s.info.get("image", ""), "unauthorized", "")
            raise ProtocolError(ErrorCode.UNAUTHORIZED, "The token is not valid for this Glass installation.")
        s.client, s.scopes = auth
        return {"protocol": ipc.PROTOCOL_VERSION, "server": "Glass.Automation", "server_version": __version__,
                "session": s.id, "client": s.client, "scopes": s.scopes, "capabilities": CAPABILITIES,
                "stopped": self.store.stopped()}

    def _admin(self, s: Session, method: str, p: dict) -> dict:
        if s.client != "owner":
            raise ProtocolError(ErrorCode.FORBIDDEN_SCOPE, "admin methods need the owner token")
        if method == "admin.stop" or method == "admin.resume":
            stop = method == "admin.stop"
            self.store.set_stopped(stop)
            self.store.audit("owner", method, "", "ok", "")
            self._broadcast_admin("stopped", {"stopped": stop})
            if stop:
                self._set_control(None)
            self.stoppedChanged.emit(stop)
            return {"stopped": stop}
        if method == "admin.subscribe":
            s.admin_subscribed = True
            return {"subscribed": True, "stopped": self.store.stopped(), "control_state": self._control_state()}
        result = self.engine.admin(method, p)
        if method == "admin.permissions.set" and "scopes" in result:
            client = str(p.get("client") or "garvis")
            for other in self.sessions.values():
                if other.client == client:
                    other.scopes = list(result["scopes"])
        return result

    # ------------------------------------------------------------------ notifications
    def _broadcast_admin(self, method: str, params: dict) -> None:
        for s in list(self.sessions.values()):
            if s.admin_subscribed:
                self._send(s, ipc.notification(method, params))

    @Slot(object)
    def _on_activity(self, a: dict) -> None:
        a = dict(a, time=time.time())
        self._broadcast_admin("activity", a)
        if a.get("outcome") == "ok" and a.get("client") != "owner":
            self._set_control({"active": True, "client": a.get("client"), "app": a.get("app", ""),
                               "title": a.get("title", "")})

    def _control_state(self) -> dict:
        return self._control_active or {"active": False}

    def _set_control(self, state: dict | None) -> None:
        if state:
            changed = (self._control_active or {}).get("app") != state.get("app") or not self._control_active
            self._control_active = state
            self._control_timer.start(CONTROL_IDLE_MS)
            if changed:
                self._broadcast_admin("control_state", state)
        elif self._control_active:
            self._control_active = None
            self._control_timer.stop()
            self._broadcast_admin("control_state", {"active": False})

    @Slot()
    def _control_idle(self) -> None:
        self._set_control(None)

    @Slot(object, object)
    def _on_event(self, sub, ev: dict) -> None:
        s = self.sessions.get(sub.session)
        if s:
            self._send(s, ipc.notification("event", ev))
